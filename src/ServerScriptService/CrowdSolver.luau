--!native
-- Решатель толпы на точках (план «Точечная физика жуков», шаг 1).
--
-- Жук здесь — хребет из 1–3 шаров вдоль его капсулы (голова, середина, брюшко). У каждой
-- точки есть положение, скорость и обратная масса. Шаг один на всех: точки летят по инерции
-- (тяжесть, сцепление лап с опорой тянет скорость к желаемой), потом связи возвращают их туда,
-- где им можно быть: хребет держит форму и разворачивает тело, шары разных жуков не
-- пересекаются, точка не ниже пола, тело не в стене и не в постройке.
--
-- Модуль не знает про Instance, жуков, маршруты и турели: получает тела и желаемые скорости,
-- отдаёт положения. Мир он спрашивает через hooks:
--   ground(x, z) -> y            высота опоры под точкой (пол, обломки, постройки жуков);
--   turnStep(angle, dt) -> угол  на сколько тело может довернуться за dt;
--   bound(user, x, z, fx, fz, dt) -> x, z   куда тело пускают стены и постройки (по центру).
-- Поэтому его можно гонять в Lune на сцене из чисел (tools/crowd_solver_test.luau).
--
-- Все данные — плоские массивы чисел по номеру тела и номеру точки. Точки тела b лежат
-- подряд с номера (b - 1) * 3 + 1, их n[b] штук. Числа — PhysicsFX.crowd, своих здесь нет.
local CrowdSolver = {}
CrowdSolver.__index = CrowdSolver

local STRIDE = 3 -- мест под точки на одно тело

-- Массивы по телу и по точке: по ним же снятие тела переставляет последнее на его место.
local BODY_KEYS = {
	"user", "n", "meanOff", "driveX", "driveZ", "wantFx", "wantFz", "fx", "fz", "axisX", "axisZ",
	"kin", "fresh", "stuck", "stuckExtra", "shake", "shakeX", "shakeZ", "side", "supported",
	"pressing", "pressX", "pressZ", "dodge", "progress",
}
local POINT_KEYS = {
	"px", "py", "pz", "ox", "oy", "oz", "vx", "vy", "vz", "off", "r", "hc", "hs", "lift", "w", "gr", "climb",
}

function CrowdSolver.new(config, hooks)
	local self = setmetatable({}, CrowdSolver)
	self.cfg = config
	self.ground = hooks.ground
	self.turnStep = hooks.turnStep
	self.bound = hooks.bound
	self.count = 0
	self.maxR = 0
	for _, key in BODY_KEYS do
		self[key] = {}
	end
	for _, key in POINT_KEYS do
		self[key] = {}
	end
	self.cells = {}
	self.cellNext = {}
	self.pairA = {}
	self.pairB = {}
	self.pairCount = 0
	-- Для отладочного вывода: сколько контактов было за все подшаги и сколько подшагов.
	self.contacts = 0
	self.substeps = 0
	return self
end

-- Новое тело. Пивот (x, y, z), ход (fx, fz) — единичный, по горизонтали. radius — ширина капсулы,
-- front/back — торцы вдоль хода от пивота, shellTop — верх спины над пивотом, lift — на сколько
-- пивот над опорой (ступни). mass — масса тела (по умолчанию у всех 1). Возвращает номер тела.
function CrowdSolver:add(user, x, y, z, fx, fz, radius, front, back, shellTop, lift, mass)
	local b = self.count + 1
	self.count = b
	local cfg = self.cfg

	local length = front - back
	local offs
	if length < 0.2 then
		offs = { (front + back) / 2 }
	elseif length > 2 * radius then
		-- Длинное тело: средняя точка, чтобы сосед не вклинивался в бок между шарами.
		offs = { front, (front + back) / 2, back }
	else
		offs = { front, back }
	end
	local n = #offs
	local mean = 0
	for _, o in offs do
		mean += o
	end
	mean /= n

	self.user[b] = user
	self.n[b] = n
	self.meanOff[b] = mean
	self.driveX[b], self.driveZ[b] = 0, 0
	self.wantFx[b], self.wantFz[b] = fx, fz
	self.fx[b], self.fz[b] = fx, fz
	self.axisX[b], self.axisZ[b] = fx, fz
	self.kin[b] = true -- до первого привода стоит, где поставили
	self.fresh[b] = false
	self.stuck[b] = 0
	self.stuckExtra[b] = math.random() * cfg.shakeSpread
	self.shake[b] = 0
	self.shakeX[b], self.shakeZ[b] = 0, 0
	self.side[b] = math.random() < 0.5 and -1 or 1
	self.supported[b] = true
	self.pressing[b] = false
	self.pressX[b], self.pressZ[b] = 0, 0
	self.dodge[b] = 0
	self.progress[b] = 0

	-- Объём по высоте — от ступней (пивот минус lift) до верха спины: под брюхом крупного
	-- мелкий не проходит, там его лапы (как в старой толкучке).
	local hc = (shellTop - lift) / 2
	local hs = math.max((shellTop + lift) / 2, 0.1)
	local w = n / (mass or 1)
	local base = (b - 1) * STRIDE
	for k = 1, STRIDE do
		local i = base + k
		local o = offs[k] or mean
		self.off[i] = o
		self.px[i], self.py[i], self.pz[i] = x + fx * o, y, z + fz * o
		self.ox[i], self.oy[i], self.oz[i] = self.px[i], y, self.pz[i]
		self.vx[i], self.vy[i], self.vz[i] = 0, 0, 0
		self.r[i] = radius
		self.hc[i] = hc
		self.hs[i] = hs
		self.lift[i] = lift
		self.w[i] = w
		self.gr[i] = y
		self.climb[i] = 0
	end
	self.maxR = math.max(self.maxR, radius)
	return b
end

-- Снять тело. Последнее тело встаёт на его место: возвращается его user, чтобы владелец
-- поправил у себя номер (или nil, если снятое и было последним).
function CrowdSolver:remove(b)
	local last = self.count
	if b < 1 or b > last then
		return nil
	end
	local moved = nil
	if b ~= last then
		for _, key in BODY_KEYS do
			local a = self[key]
			a[b] = a[last]
		end
		local to, from = (b - 1) * STRIDE, (last - 1) * STRIDE
		for _, key in POINT_KEYS do
			local a = self[key]
			for k = 1, STRIDE do
				a[to + k] = a[from + k]
			end
		end
		moved = self.user[b]
	end
	for _, key in BODY_KEYS do
		self[key][last] = nil
	end
	local from = (last - 1) * STRIDE
	for _, key in POINT_KEYS do
		local a = self[key]
		for k = 1, STRIDE do
			a[from + k] = nil
		end
	end
	self.count = last - 1
	return moved
end

function CrowdSolver:clear()
	for _, key in BODY_KEYS do
		table.clear(self[key])
	end
	for _, key in POINT_KEYS do
		table.clear(self[key])
	end
	table.clear(self.cells)
	table.clear(self.cellNext)
	self.count = 0
	self.pairCount = 0
	self.maxR = 0
end

-- Поставить тело руками (перелезание, подброс, перенос): точки встают по пивоту и ходу,
-- скорость гаснет. До следующего привода тело ведомое: другим помеха, само не двигается.
function CrowdSolver:place(b, x, y, z, fx, fz)
	fx, fz = fx or self.fx[b], fz or self.fz[b]
	local base = (b - 1) * STRIDE
	for k = 1, self.n[b] do
		local i = base + k
		local o = self.off[i]
		self.px[i], self.py[i], self.pz[i] = x + fx * o, y, z + fz * o
		self.ox[i], self.oy[i], self.oz[i] = self.px[i], y, self.pz[i]
		self.vx[i], self.vy[i], self.vz[i] = 0, 0, 0
		self.climb[i] = 0
	end
	self.fx[b], self.fz[b] = fx, fz
	self.axisX[b], self.axisZ[b] = fx, fz
	self.wantFx[b], self.wantFz[b] = fx, fz
	self.kin[b] = true
	self.fresh[b] = false
	self.stuck[b] = 0
	self.shake[b] = 0
end

-- Привод на следующий шаг: желаемая скорость по горизонтали и куда тело хочет смотреть.
function CrowdSolver:drive(b, vx, vz, wantFx, wantFz)
	self.driveX[b], self.driveZ[b] = vx, vz
	if wantFx then
		self.wantFx[b], self.wantFz[b] = wantFx, wantFz
	end
	self.kin[b] = false
	self.fresh[b] = true
end

-- Пивот тела и его ход: из точек обратно в кадр жука. Пивот лежит на оси хребта
-- (с наклоном), ход — по горизонтали.
function CrowdSolver:pivot(b)
	local n = self.n[b]
	local base = (b - 1) * STRIDE
	local px, py, pz = self.px, self.py, self.pz
	local cx, cy, cz = 0, 0, 0
	for k = 1, n do
		local i = base + k
		cx += px[i]
		cy += py[i]
		cz += pz[i]
	end
	cx, cy, cz = cx / n, cy / n, cz / n
	local fx, fz = self.fx[b], self.fz[b]
	local ax, ay, az = fx, 0, fz
	if n >= 2 then
		local f, t = base + 1, base + n
		local dx, dy, dz = px[f] - px[t], py[f] - py[t], pz[f] - pz[t]
		local len = math.sqrt(dx * dx + dy * dy + dz * dz)
		if len > 1e-4 then
			ax, ay, az = dx / len, dy / len, dz / len
		end
	end
	local mean = self.meanOff[b]
	return cx - ax * mean, cy - ay * mean, cz - az * mean, fx, fz
end

-- С какой скоростью тело продвигается туда, куда хочет (studs/сек).
function CrowdSolver:advance(b)
	return self.progress[b]
end

local function cellKey(x, z, cell)
	return (math.floor(x / cell) + 32768) * 65536 + math.floor(z / cell) + 32768
end

-- Один подшаг длиной h.
function CrowdSolver:substep(h)
	local cfg = self.cfg
	local count = self.count
	local n, kin, user = self.n, self.kin, self.user
	local px, py, pz = self.px, self.py, self.pz
	local ox, oy, oz = self.ox, self.oy, self.oz
	local vx, vy, vz = self.vx, self.vy, self.vz
	local off, r, hc, hs, lift, w, gr, climb = self.off, self.r, self.hc, self.hs, self.lift, self.w, self.gr, self.climb
	local driveX, driveZ, wantFx, wantFz = self.driveX, self.driveZ, self.wantFx, self.wantFz
	local axisX, axisZ, fxs, fzs, meanOff = self.axisX, self.axisZ, self.fx, self.fz, self.meanOff
	local stuck, stuckExtra, shake, shakeX, shakeZ, side = self.stuck, self.stuckExtra, self.shake, self.shakeX, self.shakeZ, self.side
	local supported, pressing, pressX, pressZ, progress = self.supported, self.pressing, self.pressX, self.pressZ, self.progress
	local dodge = self.dodge
	local ground, turnStep, bound = self.ground, self.turnStep, self.bound

	local gravity = cfg.gravity
	local grip = 1 - math.exp(-cfg.traction * h)
	local drag = 1 - math.exp(-cfg.airDrag * h)
	local climbSpeed = cfg.climbSpeed
	local minDrive = cfg.minDrive

	-- 1. Разворот, затор, инерция.
	for b = 1, count do
		local base = (b - 1) * STRIDE
		local nb = n[b]
		if kin[b] then
			for k = 1, nb do
				local i = base + k
				ox[i], oy[i], oz[i] = px[i], py[i], pz[i]
				vx[i], vy[i], vz[i] = 0, 0, 0
			end
		else
			-- Ход тела сейчас — от брюшка к голове; доворачивается к желаемому не быстрее,
			-- чем видимое тело (тот же turnStep, что у походки).
			local ax, az = fxs[b], fzs[b]
			if nb >= 2 then
				local dx, dz = px[base + 1] - px[base + nb], pz[base + 1] - pz[base + nb]
				local len = math.sqrt(dx * dx + dz * dz)
				if len > 1e-3 then
					ax, az = dx / len, dz / len
				end
			end
			local wx, wz = wantFx[b], wantFz[b]
			local angle = math.atan2(ax * wz - az * wx, ax * wx + az * wz)
			local turn = turnStep(angle, h)
			if math.abs(angle) > turn then
				angle = math.sign(angle) * turn
			end
			local c, s = math.cos(angle), math.sin(angle)
			ax, az = c * ax - s * az, s * ax + c * az
			axisX[b], axisZ[b] = ax, az

			-- Затор: давит в того, кто впереди, и почти не продвигается — копит «застревание».
			-- Сначала лезет на спину (climbDelay, см. контакты ниже), дольше — встряска:
			-- шаг назад и вбок прочь от тех, кто жмёт (нынешний «затор и отступ»).
			local dvx, dvz = driveX[b], driveZ[b]
			local want = math.sqrt(dvx * dvx + dvz * dvz)
			if want > minDrive and pressing[b] and progress[b] < want * cfg.stuckProgress then
				stuck[b] += h
			else
				stuck[b] = math.max(0, stuck[b] - 2 * h)
			end
			if want > minDrive and stuck[b] >= cfg.shakeTime + stuckExtra[b] then
				local sd = side[b]
				local ux, uz = dvx / want, dvz / want
				local bx = -ux * cfg.shakeBack + pressX[b] - uz * sd
				local bz = -uz * cfg.shakeBack + pressZ[b] + ux * sd
				local len = math.sqrt(bx * bx + bz * bz)
				if len > 1e-3 then
					shakeX[b], shakeZ[b] = bx / len, bz / len
					shake[b] = cfg.shakeDuration
				end
				stuck[b] = 0
			end
			if shake[b] > 0 then
				-- Встряхиваясь, жук не ломится по маршруту, а сдаёт прочь: иначе арку в проёме
				-- держат те же, кто давит.
				shake[b] -= h
				dvx = shakeX[b] * cfg.shakeSpeed
				dvz = shakeZ[b] * cfg.shakeSpeed
			end

			-- Обгон: упёршись в того, кто впереди, жук берёт вбок — на ту сторону, где он и так
			-- чуть левее или правее соседа. Так толпа течёт рядами и обтекает, а не стоит колонной.
			local side = dodge[b]
			if side ~= 0 and shake[b] <= 0 and want > minDrive then
				local push = cfg.sidestep * want * math.sign(side)
				dvx += -driveZ[b] / want * push
				dvz += driveX[b] / want * push
			end

			-- Сцепление: лапы на опоре тянут скорость к желаемой; в воздухе только сопротивление.
			local onGround = supported[b]
			for k = 1, nb do
				local i = base + k
				ox[i], oy[i], oz[i] = px[i], py[i], pz[i]
				local x, y, z = vx[i], vy[i] - gravity * h, vz[i]
				if onGround then
					x += (dvx - x) * grip
					z += (dvz - z) * grip
				else
					x -= x * drag
					z -= z * drag
				end
				if climb[i] == 1 then
					-- Подъём на спину соседа: точка, упёршаяся в него, тянется вверх.
					if y < climbSpeed then
						y = climbSpeed
					end
					climb[i] = 0
				end
				vx[i], vy[i], vz[i] = x, y, z
				px[i] += x * h
				py[i] += y * h
				pz[i] += z * h
				gr[i] = ground(px[i], pz[i]) + lift[i]
			end
			supported[b] = false
			pressing[b] = false
			pressX[b], pressZ[b] = 0, 0
			dodge[b] = 0
		end
	end

	-- 2. Пары точек, которые могут коснуться за этот подшаг: корзины cell x cell.
	local cell = cfg.cell
	local cells, nextIn = self.cells, self.cellNext
	table.clear(cells)
	for b = 1, count do
		local base = (b - 1) * STRIDE
		for k = 1, n[b] do
			local i = base + k
			local key = cellKey(px[i], pz[i], cell)
			nextIn[i] = cells[key] or 0
			cells[key] = i
		end
	end
	local margin = cfg.pairMargin
	local span = math.ceil((2 * self.maxR + margin) / cell)
	local pairA, pairB = self.pairA, self.pairB
	local pairs = 0
	for b = 1, count do
		local base = (b - 1) * STRIDE
		local kb = kin[b]
		for k = 1, n[b] do
			local i = base + k
			local x, y, z = px[i], py[i] + hc[i], pz[i]
			local ri, hi = r[i], hs[i]
			local cx0, cz0 = math.floor(x / cell), math.floor(z / cell)
			for cx = cx0 - span, cx0 + span do
				for cz = cz0 - span, cz0 + span do
					local j = cells[(cx + 32768) * 65536 + cz + 32768] or 0
					while j ~= 0 do
						if j > i then
							local bj = (j - 1) // STRIDE + 1
							if bj ~= b and not (kb and kin[bj]) then
								local reach = ri + r[j] + margin
								local dx, dz = x - px[j], z - pz[j]
								local dy = y - py[j] - hc[j]
								local tall = hi + hs[j] + margin
								if dx * dx + dz * dz < reach * reach and dy < tall and dy > -tall then
									pairs += 1
									pairA[pairs], pairB[pairs] = i, j
								end
							end
						end
						j = nextIn[j]
					end
				end
			end
		end
	end
	self.pairCount = pairs

	-- 3. Связи, несколько проходов.
	local stiff = cfg.spineStiffness
	local maxSin = cfg.maxPitch
	local limit = 1 - cfg.contactSlop
	local aheadDot = cfg.aheadDot
	local climbDelay, climbAbove = cfg.climbDelay, cfg.climbAbove
	-- Лезут только на того, кто сам стоит на полу: куча в два яруса, а не башня.
	local climbOnGround = cfg.climbOnGround
	local maxLayers = cfg.maxLayers
	local touching = 0
	for pass = 1, cfg.iterations do
		-- Хребет: точки тела стоят на одной прямой на своих местах. Поворот вокруг
		-- вертикали задаёт ход (axis), наклон — сами точки (разная высота опоры).
		for b = 1, count do
			local nb = n[b]
			if nb >= 2 and not kin[b] then
				local base = (b - 1) * STRIDE
				local cx, cy, cz = 0, 0, 0
				for k = 1, nb do
					local i = base + k
					cx += px[i]
					cy += py[i]
					cz += pz[i]
				end
				cx, cy, cz = cx / nb, cy / nb, cz / nb
				local f, t = base + 1, base + nb
				local hx, hz = px[f] - px[t], pz[f] - pz[t]
				local hl = math.sqrt(hx * hx + hz * hz)
				local dy = py[f] - py[t]
				local len = math.sqrt(hl * hl + dy * dy)
				local sinT = len > 1e-4 and dy / len or 0
				sinT = math.clamp(sinT, -maxSin, maxSin)
				local cosT = math.sqrt(1 - sinT * sinT)
				local ax, ay, az = axisX[b] * cosT, sinT, axisZ[b] * cosT
				local mean = meanOff[b]
				for k = 1, nb do
					local i = base + k
					local o = off[i] - mean
					px[i] += (cx + ax * o - px[i]) * stiff
					py[i] += (cy + ay * o - py[i]) * stiff
					pz[i] += (cz + az * o - pz[i]) * stiff
				end
			end
		end

		-- Тело об тело: шары сплюснуты по высоте (эллипсоиды), сдвиг делится по массе.
		for p = 1, pairs do
			local i, j = pairA[p], pairB[p]
			local bi, bj = (i - 1) // STRIDE + 1, (j - 1) // STRIDE + 1
			local wi = kin[bi] and 0 or w[i]
			local wj = kin[bj] and 0 or w[j]
			local wsum = wi + wj
			if wsum > 0 then
				local dx, dz = px[i] - px[j], pz[i] - pz[j]
				local dy = py[i] + hc[i] - py[j] - hc[j]
				local R, H = r[i] + r[j], hs[i] + hs[j]
				local flat2 = (dx * dx + dz * dz) / (R * R)
				local up2 = dy * dy / (H * H)
				local q2 = flat2 + up2
				if q2 < limit * limit then
					if q2 < 1e-8 then
						-- Центры совпали: направление берётся из номеров, лишь бы разное у двоих.
						dx, dz = math.cos(i) * R * 0.01, math.sin(i) * R * 0.01
						flat2 = 1e-4
						q2 = 1e-4
					end
					local q = math.sqrt(q2)
					local scale = limit / q - 1
					local cx, cy, cz = dx * scale, dy * scale, dz * scale
					local si, sj = wi / wsum, wj / wsum
					px[i] += cx * si
					py[i] += cy * si
					pz[i] += cz * si
					px[j] -= cx * sj
					py[j] -= cy * sj
					pz[j] -= cz * sj

					-- Кто сверху (контакт больше вертикальный, чем боковой), тот стоит на соседе.
					if up2 > flat2 then
						if dy > 0 then
							supported[bi] = true
						else
							supported[bj] = true
						end
					end

					if pass == 1 then
						touching += 1
						-- Давит в соседа своим приводом: копит затор, а застряв — лезет ему на спину,
						-- если ещё не выше него.
						local fl = math.sqrt(dx * dx + dz * dz)
						if fl > 1e-4 then
							local nx, nz = dx / fl, dz / fl
							local dvx, dvz = driveX[bi], driveZ[bi]
							local want = math.sqrt(dvx * dvx + dvz * dvz)
							if wi > 0 and want > minDrive and (dvx * nx + dvz * nz) < -aheadDot * want then
								pressing[bi] = true
								pressX[bi] += nx
								pressZ[bi] += nz
								-- Сторона обгона: где i относительно j поперёк своего хода.
								local across = (-dvz * dx + dvx * dz) / want
								dodge[bi] += if across > 0.05 then 1 elseif across < -0.05 then -1 else side[bi]
								if stuck[bi] >= climbDelay and dy < H * climbAbove and py[j] - gr[j] < climbOnGround then
									climb[i] = 1
								end
							end
							dvx, dvz = driveX[bj], driveZ[bj]
							want = math.sqrt(dvx * dvx + dvz * dvz)
							if wj > 0 and want > minDrive and (dvx * nx + dvz * nz) > aheadDot * want then
								pressing[bj] = true
								pressX[bj] -= nx
								pressZ[bj] -= nz
								local across = (dvz * dx - dvx * dz) / want
								dodge[bj] += if across > 0.05 then 1 elseif across < -0.05 then -1 else side[bj]
								if stuck[bj] >= climbDelay and -dy < H * climbAbove and py[i] - gr[i] < climbOnGround then
									climb[j] = 1
								end
							end
						end
					end
				end
			end
		end

		-- Опора: точка не ниже пола под ней. И не выше maxLayers ростов тела над ним: давка
		-- клиньями выжимает тела вверх, и без потолка куча у стены росла башней.
		for b = 1, count do
			if not kin[b] then
				local base = (b - 1) * STRIDE
				for k = 1, n[b] do
					local i = base + k
					local floor = gr[i]
					if py[i] < floor then
						py[i] = floor
						supported[b] = true
					else
						local top = floor + maxLayers * 2 * hs[i]
						if py[i] > top then
							py[i] = top
						end
					end
				end
			end
		end
	end
	self.contacts += touching
	self.substeps += 1

	-- 4. Стены и постройки — по центру тела, всё тело сдвигается на ту же поправку.
	-- 5. Скорость — из того, куда точки пришли.
	local maxRise, maxFall, maxSpeed = cfg.maxRise, cfg.maxFall, cfg.maxSpeed
	for b = 1, count do
		if not kin[b] then
			local base = (b - 1) * STRIDE
			local nb = n[b]
			local ax, az = axisX[b], axisZ[b]
			if nb >= 2 then
				local dx, dz = px[base + 1] - px[base + nb], pz[base + 1] - pz[base + nb]
				local len = math.sqrt(dx * dx + dz * dz)
				if len > 1e-3 then
					ax, az = dx / len, dz / len
				end
			end
			fxs[b], fzs[b] = ax, az

			if bound then
				local cx, cz = 0, 0
				for k = 1, nb do
					cx += px[base + k]
					cz += pz[base + k]
				end
				local mean = meanOff[b]
				cx, cz = cx / nb - ax * mean, cz / nb - az * mean
				local x, z = bound(user[b], cx, cz, ax, az, h)
				local sx, sz = x - cx, z - cz
				if sx ~= 0 or sz ~= 0 then
					for k = 1, nb do
						px[base + k] += sx
						pz[base + k] += sz
					end
				end
			end

			local dvx, dvz = driveX[b], driveZ[b]
			local want = math.sqrt(dvx * dvx + dvz * dvz)
			local along = 0
			for k = 1, nb do
				local i = base + k
				local x, y, z = (px[i] - ox[i]) / h, (py[i] - oy[i]) / h, (pz[i] - oz[i]) / h
				if y > maxRise then
					y = maxRise
				elseif y < -maxFall then
					y = -maxFall
				end
				local speed = math.sqrt(x * x + z * z)
				if speed > maxSpeed then
					x, z = x / speed * maxSpeed, z / speed * maxSpeed
				end
				vx[i], vy[i], vz[i] = x, y, z
				if want > 1e-3 then
					along += (x * dvx + z * dvz) / want
				end
			end
			progress[b] = math.max(0, along / nb)
		end
	end
end

-- Шаг на время кадра dt: кадр делится на равные подшаги не длиннее cfg.step, их не больше
-- cfg.maxSubsteps. Долг времени не копится: на просевшем сервере жуки идут медленнее,
-- а не рывками догоняют. Тело, которому с прошлого шага не дали привода, ведомое.
-- Возвращает число подшагов.
function CrowdSolver:step(dt)
	local cfg = self.cfg
	dt = math.min(dt, cfg.step * cfg.maxSubsteps)
	if dt <= 0 or self.count == 0 then
		return 0
	end
	local kin, fresh = self.kin, self.fresh
	for b = 1, self.count do
		if not fresh[b] then
			kin[b] = true
		end
		fresh[b] = false
	end
	local subs = math.max(1, math.ceil(dt / cfg.step - 1e-6))
	local h = dt / subs
	for _ = 1, subs do
		self:substep(h)
	end
	return subs
end

-- Точки тела: для отладочных шаров и проверок. Возвращает n и функцию point(k) -> x, y, z,
-- радиус, вертикальный центр над точкой, вертикальная полуось.
function CrowdSolver:points(b)
	local base = (b - 1) * STRIDE
	return self.n[b], function(k)
		local i = base + k
		return self.px[i], self.py[i], self.pz[i], self.r[i], self.hc[i], self.hs[i]
	end
end

return CrowdSolver
