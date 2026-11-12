--!native
-- Решатель толпы на точках (план «Точечная физика жуков», шаги 1–4).
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
--   bound(user, x, z, fx, fz, dt, above) -> x, z   куда пускают центр тела (край пола арены).
-- Твёрдое — ещё два источника, их владелец отдаёт решателю заранее (шаг 3):
--   setField   — запечённая карта расстояний до неподвижных стен и мебели (2D, клетка 1 stud);
--   setBoxes   — постройки и стол: прямоугольники следа с верхом и щелью для подлаза.
-- Каждая точка выталкивается из них сама, по своему радиусу.
-- Поэтому его можно гонять в Lune на сцене из чисел (tools/crowd_solver_test.luau).
--
-- Убитый жук остаётся телом-трупом (kill, шаг 4): привода нет, его несёт то, что было, его
-- толкают живые, и он лежит, пока не остановится (resting) — тогда владелец снимает его.
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
	"air", "roll", "rollVel", "flip", "heavy",
	"climbV", "climbTop", "bodyH", "perch", "pitchMax",
	"dead", "still",
}
local POINT_KEYS = {
	"px", "py", "pz", "ox", "oy", "oz", "vx", "vy", "vz", "off", "r", "hc", "hs", "lift", "w", "gr", "gb", "climb",
}

-- Состояние тела для владельца (поза походки): на полу, на стене постройки, на её крыше.
CrowdSolver.GROUND, CrowdSolver.WALL, CrowdSolver.TOP = 0, 1, 2

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
	-- Постройки (setBoxes) и карта стен (setField).
	self.boxCount = 0
	self.boxMinX, self.boxMaxX, self.boxMinZ, self.boxMaxZ = {}, {}, {}, {}
	self.boxTop, self.boxGap = {}, {}
	self.boxCells = {}
	self.field = nil
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
function CrowdSolver:add(user, x, y, z, fx, fz, radius, front, back, shellTop, lift, mass, bodyHeight)
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
	self.air[b] = false -- летит от толчка: без сцепления, без потолка подъёма
	self.roll[b] = 0 -- крен, рад: кувырок в полёте, на спине больше пол-оборота
	self.rollVel[b] = 0
	self.flip[b] = 0 -- сколько секунд лежит на спине
	self.heavy[b] = 1 -- во сколько раз тяжелее обычного сейчас (грызёт, разгон)
	self.climbV[b] = 0 -- можно лезть на постройки: скорость подъёма (0 — нельзя)
	self.climbTop[b] = 0 -- и на какую высоту над полом
	self.bodyH[b] = bodyHeight or (shellTop + lift) -- высота спины: пролезет ли под постройкой
	self.perch[b] = 0
	self.pitchMax[b] = cfg.maxPitch
	self.progress[b] = 0
	self.dead[b] = false -- труп (шаг 4): без привода, лежит, пока не остановится
	self.still[b] = 0 -- сколько секунд труп почти не движется

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
		self.gb[i] = y
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
	self.air[b] = false
	self.roll[b], self.rollVel[b], self.flip[b] = 0, 0, 0
	self.perch[b] = 0
	self.still[b] = 0
end

-- Разрешить телу лезть на постройки (маршрут велит перелезть): скорость подъёма и высота
-- над полом, выше которой не лезет. speed 0 — нельзя: постройка для него стена до неба.
-- С разрешением крыша постройки для тела — пол, а спуск с неё — не быстрее подъёма.
function CrowdSolver:allowClimb(b, speed, height)
	self.climbV[b] = speed or 0
	self.climbTop[b] = height or 0
end

-- На полу, на стене или на крыше (CrowdSolver.GROUND / WALL / TOP).
function CrowdSolver:perchOf(b)
	return self.perch[b]
end

-- Постройки: список { minX, maxX, minZ, maxZ, top, gap } — след, абсолютная высота верха
-- (math.huge — не лезут) и щель снизу (тело ниже неё пролезает, 0 — нет щели).
function CrowdSolver:setBoxes(list)
	local count = #list
	self.boxCount = count
	local minX, maxX, minZ, maxZ, top, gap = self.boxMinX, self.boxMaxX, self.boxMinZ, self.boxMaxZ, self.boxTop, self.boxGap
	table.clear(minX)
	table.clear(maxX)
	table.clear(minZ)
	table.clear(maxZ)
	table.clear(top)
	table.clear(gap)
	local cells = self.boxCells
	table.clear(cells)
	local cell = self.cfg.cell
	for k, box in list do
		minX[k], maxX[k], minZ[k], maxZ[k] = box.minX, box.maxX, box.minZ, box.maxZ
		top[k], gap[k] = box.top or math.huge, box.gap or 0
		-- В корзины, которые след накрывает: точка ищет постройки только в своей корзине,
		-- поэтому след раздут на самый крупный радиус точки с запасом.
		local pad = 4
		for cx = math.floor((box.minX - pad) / cell), math.floor((box.maxX + pad) / cell) do
			for cz = math.floor((box.minZ - pad) / cell), math.floor((box.maxZ + pad) / cell) do
				local key = (cx + 32768) * 65536 + cz + 32768
				local listIn = cells[key]
				if not listIn then
					listIn = {}
					cells[key] = listIn
				end
				table.insert(listIn, k)
			end
		end
	end
end

-- Карта расстояний до стен: { x0, z0, w, h, cell, data } — data[(row) * w + col + 1] —
-- расстояние от центра клетки до ближайшей стены (внутри стены — минус). nil — стен нет.
function CrowdSolver:setField(field)
	self.field = field
end

-- Расстояние до стены в точке (билинейно) или nil, если точка вне карты.
local function sampleField(field, x, z)
	local cell = field.cell
	local fx = (x - field.x0) / cell
	local fz = (z - field.z0) / cell
	local w, hgt = field.w, field.h
	if fx < 0 or fz < 0 or fx >= w - 1 or fz >= hgt - 1 then
		return nil
	end
	local c0, r0 = math.floor(fx), math.floor(fz)
	local tx, tz = fx - c0, fz - r0
	local data = field.data
	local i = r0 * w + c0 + 1
	local a, b2 = data[i], data[i + 1]
	local c, d = data[i + w], data[i + w + 1]
	return (a * (1 - tx) + b2 * tx) * (1 - tz) + (c * (1 - tx) + d * tx) * tz
end
CrowdSolver.sampleField = sampleField

function CrowdSolver:wallDistance(x, z)
	return self.field and sampleField(self.field, x, z)
end

-- Привод на следующий шаг: желаемая скорость по горизонтали и куда тело хочет смотреть.
-- heavy — во сколько раз тело сейчас тяжелее обычного (грызёт, разгон Тарана): толпа его
-- двигает во столько же раз меньше.
function CrowdSolver:drive(b, vx, vz, wantFx, wantFz, heavy)
	self.heavy[b] = heavy or 1
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

-- Летит ли тело от толчка (ещё не приземлилось).
function CrowdSolver:airborne(b)
	return self.air[b]
end

-- Средняя скорость точек тела и скорость крена: с ними клиент запускает тушу (шаг 4).
function CrowdSolver:velocity(b)
	local n = self.n[b]
	local base = (b - 1) * STRIDE
	local x, y, z = 0, 0, 0
	for k = 1, n do
		local i = base + k
		x += self.vx[i]
		y += self.vy[i]
		z += self.vz[i]
	end
	return x / n, y / n, z / n, self.rollVel[b]
end

-- Жук умер: тело остаётся в толпе трупом. Привода нет, лезть нельзя, с ведомого снимается
-- неподвижность: дальше его несёт то, что у него было, тяжесть, опора и соседи.
function CrowdSolver:kill(b)
	self.dead[b] = true
	self.still[b] = 0
	self.driveX[b], self.driveZ[b] = 0, 0
	self.wantFx[b], self.wantFz[b] = self.fx[b], self.fz[b]
	self.climbV[b], self.climbTop[b] = 0, 0
	self.heavy[b] = 1
	self.stuck[b], self.shake[b], self.dodge[b] = 0, 0, 0
	self.kin[b] = false
end

-- Труп лёг: на опоре и почти не движется уже cfg.restTime секунд.
function CrowdSolver:resting(b)
	return self.dead[b] and self.still[b] >= self.cfg.restTime
end

-- Толчок: прибавка скорости всем точкам тела. Вверх — отрыв от опоры, дальше тяжесть.
-- spin — прибавка скорости крена (рад/сек): кувырок.
function CrowdSolver:knock(b, vx, vy, vz, spin)
	local base = (b - 1) * STRIDE
	for k = 1, self.n[b] do
		local i = base + k
		self.vx[i] += vx
		self.vy[i] += vy
		self.vz[i] += vz
	end
	if vy > 0 then
		self.air[b] = true
		self.supported[b] = false
	end
	self.rollVel[b] += spin or 0
	self.kin[b] = false
end

-- Скорость толчка, с которой одиночное тело на ровном полу уходит на distance studs:
-- горизонтальная и вертикальная. Малый толчок — скольжение по полу (его гасит сцепление),
-- больший — отрыв с подъёмом knockLift от горизонтали: полёт по дуге (с сопротивлением
-- воздуха) и скольжение после посадки. Скольжение считается так же, как его шагает решатель
-- (подшаг cfg.step); горизонталь подбирается делением пополам — толчок редкий, это дёшево.
function CrowdSolver.knockVelocity(cfg, distance)
	local h = cfg.step
	local a = math.exp(-cfg.traction * h)
	local slide = h * a / (1 - a) -- studs скольжения на каждый stud/сек скорости
	if distance < cfg.knockLiftFrom then
		return distance / slide, 0
	end
	local lift, g, k = cfg.knockLift, cfg.gravity, cfg.airDrag
	local function reach(vh)
		local t = 2 * lift * vh / g
		local keep = math.exp(-k * t)
		local air = if k > 1e-6 then vh * (1 - keep) / k else vh * t
		return air + vh * keep * slide
	end
	local lo, hi = 0, cfg.maxSpeed
	for _ = 1, 30 do
		local mid = (lo + hi) / 2
		if reach(mid) < distance * cfg.knockScale then
			lo = mid
		else
			hi = mid
		end
	end
	return lo, lo * lift
end

-- Скорость броска на высоту height, чтобы упасть в (dx, dz) от точки броска на той же
-- высоте: вверх — по тяжести, вбок — с поправкой на сопротивление воздуха.
function CrowdSolver.tossVelocity(cfg, dx, dz, height)
	local g, k = cfg.gravity, cfg.airDrag
	local up = math.sqrt(2 * g * math.max(height, 0))
	local t = math.max(2 * up / g, 1e-3)
	local per = if k > 1e-6 then k / (1 - math.exp(-k * t)) else 1 / t
	return dx * per, up, dz * per
end

-- Толчок смещением (атрибут Push: вектор в studs по горизонтали). Сильный — с кувырком
-- в случайную сторону.
function CrowdSolver:shove(b, offsetX, offsetZ)
	local distance = math.sqrt(offsetX * offsetX + offsetZ * offsetZ)
	if distance < 1e-3 then
		return
	end
	local cfg = self.cfg
	local vh, vy = CrowdSolver.knockVelocity(cfg, distance)
	local spin = 0
	if vh > cfg.tumbleFrom then
		spin = (vh - cfg.tumbleFrom) * cfg.tumble * (math.random() < 0.5 and -1 or 1)
	end
	self:knock(b, offsetX / distance * vh, vy, offsetZ / distance * vh, spin)
end

-- Наклон тела для кадра жука: куда смотрит голова (с тангажом от разной высоты точек)
-- и где у него верх (с креном кувырка).
function CrowdSolver:tilt(b)
	local n = self.n[b]
	local base = (b - 1) * STRIDE
	local ax, ay, az = self.fx[b], 0, self.fz[b]
	if n >= 2 then
		local f, t = base + 1, base + n
		local dx, dy, dz = self.px[f] - self.px[t], self.py[f] - self.py[t], self.pz[f] - self.pz[t]
		local len = math.sqrt(dx * dx + dy * dy + dz * dz)
		if len > 1e-4 then
			ax, ay, az = dx / len, dy / len, dz / len
		end
	end
	-- На стене постройки тело показывается задранным вверх по стене (wallPitch), хотя
	-- точки поднимаются вместе: так жук ползёт по стене, а хребет его не отрывает от неё.
	if self.perch[b] == CrowdSolver.WALL then
		local flat = math.sqrt(ax * ax + az * az)
		if flat > 1e-4 then
			local pitch = self.cfg.wallPitch
			ax, ay, az = ax / flat * math.cos(pitch), math.sin(pitch), az / flat * math.cos(pitch)
		end
	end
	-- Мелкий тангаж от толкотни не показывается: тело на ровном полу стоит ровно.
	if math.abs(ay) < self.cfg.pitchDeadzone then
		local flat = math.sqrt(ax * ax + az * az)
		if flat > 1e-4 then
			ax, ay, az = ax / flat, 0, az / flat
		end
	end
	-- Вправо: голова x мировой верх; верх тела: вправо x голова, повёрнутый на крен.
	local rx, rz = -az, ax
	local rl = math.sqrt(rx * rx + rz * rz)
	if rl < 1e-4 then
		rx, rz, rl = 1, 0, 1
	end
	rx, rz = rx / rl, rz / rl
	local ux, uy, uz = -rz * ay, rz * ax - rx * az, rx * ay
	local roll = self.roll[b]
	local c, s = math.cos(roll), math.sin(roll)
	return ax, ay, az, ux * c + rx * s, uy * c, uz * c + rz * s
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
	local air, rolls, rollVel, flip, heavy = self.air, self.roll, self.rollVel, self.flip, self.heavy
	local dead, still = self.dead, self.still
	local climbV, climbTop, bodyH, perch, pitchMax = self.climbV, self.climbTop, self.bodyH, self.perch, self.pitchMax
	local gb = self.gb
	local boxCount, boxCells = self.boxCount, self.boxCells
	local boxMinX, boxMaxX, boxMinZ, boxMaxZ = self.boxMinX, self.boxMaxX, self.boxMinZ, self.boxMaxZ
	local boxTop, boxGap = self.boxTop, self.boxGap
	local field = self.field
	local cell = cfg.cell
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
			if dead[b] then
				wx, wz = ax, az -- труп не доворачивается
			end
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

			-- Полёт кончается, когда тело снова на опоре. Кувырок: в полёте крен крутится,
			-- на опоре гаснет. Легший на спину (крен больше пол-оборота) лежит flipTime
			-- и не идёт, потом переворачивается обратно.
			if air[b] and supported[b] then
				air[b] = false
			end
			local roll = rolls[b]
			if air[b] then
				roll += rollVel[b] * h
			else
				rollVel[b] = 0
				if math.abs(roll) > math.pi / 2 then
					flip[b] += h
					if flip[b] >= cfg.flipTime and not dead[b] then
						roll -= math.sign(roll) * cfg.standSpeed * h
					end
					dvx, dvz = 0, 0
				else
					flip[b] = 0
					roll *= math.exp(-cfg.rollSettle * h)
				end
			end
			if roll > math.pi then
				roll -= 2 * math.pi
			elseif roll < -math.pi then
				roll += 2 * math.pi
			end
			rolls[b] = roll

			-- Обгон: упёршись в того, кто впереди, жук берёт вбок — на ту сторону, где он и так
			-- чуть левее или правее соседа. Так толпа течёт рядами и обтекает, а не стоит колонной.
			local side = dodge[b]
			if side ~= 0 and shake[b] <= 0 and want > minDrive and math.abs(roll) <= math.pi / 2 then
				local push = cfg.sidestep * want * math.sign(side)
				dvx += -driveZ[b] / want * push
				dvz += driveX[b] / want * push
			end

			perch[b] = CrowdSolver.GROUND

			-- Сцепление: лапы на опоре тянут скорость к желаемой; в воздухе только сопротивление.
			local onGround = supported[b]
			-- Слезает с крыши по разрешению: висит без опоры над полом — всё тело спускается
			-- ровно со скоростью подъёма (вниз по стене), а не падает.
			local lowering = false
			if climbV[b] > 0 and not air[b] and not onGround then
				for k = 1, nb do
					local i = base + k
					if py[i] > gb[i] + 0.05 then
						lowering = true
					end
				end
			end
			for k = 1, nb do
				local i = base + k
				ox[i], oy[i], oz[i] = px[i], py[i], pz[i]
				local x, y, z = vx[i], vy[i] - gravity * h, vz[i]
				if lowering then
					x, y, z = 0, -climbV[b], 0
				end
				if onGround then
					x += (dvx - x) * grip
					z += (dvz - z) * grip
				else
					x -= x * drag
					z -= z * drag
				end
				local up = climb[i]
				if up > 0 then
					-- Подъём на спину соседа или на стену постройки: точка, упёршаяся в него,
					-- тянется вверх со скоростью подъёма.
					if y < up then
						y = up
					end
					climb[i] = 0
				end
				vx[i], vy[i], vz[i] = x, y, z
				px[i] += x * h
				py[i] += y * h
				pz[i] += z * h
				local base0 = ground(px[i], pz[i]) + lift[i]
				gb[i] = base0
				-- Кому разрешено лезть, тому крыша постройки под ступнями — пол.
				local floor = base0
				if climbV[b] > 0 and boxCount > 0 then
					local feet = py[i] - lift[i]
					local x0, z0 = px[i], pz[i]
					local list = boxCells[(math.floor(x0 / cell) + 32768) * 65536 + math.floor(z0 / cell) + 32768]
					if list then
						-- Крыша держит точку, пока шар касается её края (на радиус касания со стеной):
						-- у кромки ступни уже на её уровне — тело шагает наверх, а не срывается вниз.
						local edge = r[i] - cfg.boxSlack + 0.05
						local ceiling = base0 - lift[i] + climbTop[b]
						for _, k in list do
							local top = boxTop[k]
							if top <= feet + cfg.stepUp and top <= ceiling + 1e-3
								and x0 > boxMinX[k] - edge and x0 < boxMaxX[k] + edge
								and z0 > boxMinZ[k] - edge and z0 < boxMaxZ[k] + edge
								and top + lift[i] > floor then
								floor = top + lift[i]
							end
						end
					end
				end
				gr[i] = floor
			end
			supported[b] = false
			pressing[b] = false
			pressX[b], pressZ[b] = 0, 0
			dodge[b] = 0
		end
	end

	-- 2. Пары точек, которые могут коснуться за этот подшаг: корзины cell x cell.
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
	local limit = 1 - cfg.contactSlop
	local aheadDot = cfg.aheadDot
	local climbDelay, climbAbove = cfg.climbDelay, cfg.climbAbove
	-- Лезут только на того, кто сам стоит на полу: куча в два яруса, а не башня.
	local climbOnGround = cfg.climbOnGround
	local maxLayers = cfg.maxLayers
	local touching = 0
	local boxSlack = cfg.boxSlack
	local stepUp = cfg.stepUp
	local boxPushMax = cfg.boxPushSpeed * h
	local WALL, TOP, GROUND = CrowdSolver.WALL, CrowdSolver.TOP, CrowdSolver.GROUND
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
				local limitSin = pitchMax[b]
				sinT = math.clamp(sinT, -limitSin, limitSin)
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
			local wi = kin[bi] and 0 or w[i] / heavy[bi]
			local wj = kin[bj] and 0 or w[j] / heavy[bj]
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
									climb[i] = climbSpeed
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
									climb[j] = climbSpeed
								end
							end
						end
					end
				end
			end
		end

		-- Постройки и стены: каждая точка выталкивается сама, по своему радиусу. Постройка —
		-- столб от пола до верха: кому лезть не разрешено, тому до неба (через неё не перелезть
		-- ни сам, ни по чужим спинам); кому разрешено и летящему — до своего верха. Упёршийся
		-- в неё по разрешению лезет вверх по стене со своей скоростью.
		if boxCount > 0 or field then
			for b = 1, count do
				if not kin[b] then
					local base = (b - 1) * STRIDE
					local climber = climbV[b] > 0
					local solidUp = not air[b] and not climber
					local dvx, dvz = driveX[b], driveZ[b]
					local want = math.sqrt(dvx * dvx + dvz * dvz)
					for k = 1, n[b] do
						local i = base + k
						local R = r[i] - boxSlack
						if boxCount > 0 then
							local list = boxCells[(math.floor(px[i] / cell) + 32768) * 65536 + math.floor(pz[i] / cell) + 32768]
							if list then
								for _, q in list do
									local top = boxTop[q]
									-- Ступни уже у края крыши (ниже не больше stepUp) — стена не держит:
									-- тело шагает на крышу, а пол под ним поднимается до её верха.
									if bodyH[b] > boxGap[q] and (solidUp or py[i] - lift[i] < top - stepUp) then
										local x, z = px[i], pz[i]
										local minX, maxX, minZ, maxZ = boxMinX[q], boxMaxX[q], boxMinZ[q], boxMaxZ[q]
										local dx = x - math.clamp(x, minX, maxX)
										local dz = z - math.clamp(z, minZ, maxZ)
										local d2 = dx * dx + dz * dz
										local nx, nz, depth = 0, 0, 0
										if d2 > 1e-8 then
											if d2 < R * R then
												local d = math.sqrt(d2)
												nx, nz, depth = dx / d, dz / d, R - d
											end
										else
											-- Точка внутри следа (постройку возвели на жука): наружу через
											-- ближний край, не рывком.
											local best = x - minX
											nx, nz = -1, 0
											if maxX - x < best then
												best, nx, nz = maxX - x, 1, 0
											end
											if z - minZ < best then
												best, nx, nz = z - minZ, 0, -1
											end
											if maxZ - z < best then
												best, nx, nz = maxZ - z, 0, 1
											end
											depth = math.min(best + R, boxPushMax)
										end
										if depth > 0 then
											px[i] += nx * depth
											pz[i] += nz * depth
											if climber and want > minDrive and (dvx * nx + dvz * nz) < -aheadDot * want
												and top - (gb[i] - lift[i]) <= climbTop[b] + 1e-3 then
												-- Лезет всем телом: лапы на стене держат его целиком, иначе
												-- хребет оттаскивал бы упёршуюся голову от стены.
												for kk = 1, n[b] do
													climb[base + kk] = climbV[b]
												end
												perch[b] = WALL
												supported[b] = true
											end
										end
									end
								end
							end
						end
						if field then
							local d = sampleField(field, px[i], pz[i])
							if d and d < R then
								local e = 0.5
								local xp, xm = sampleField(field, px[i] + e, pz[i]), sampleField(field, px[i] - e, pz[i])
								local zp, zm = sampleField(field, px[i], pz[i] + e), sampleField(field, px[i], pz[i] - e)
								if xp and xm and zp and zm then
									local gx, gz = xp - xm, zp - zm
									local gl = math.sqrt(gx * gx + gz * gz)
									if gl > 1e-5 then
										local push = math.min(R - d, boxPushMax)
										px[i] += gx / gl * push
										pz[i] += gz / gl * push
									end
								end
							end
						end
					end
				end
			end
		end

		-- Опора: точка не ниже пола под ней. И не выше maxLayers ростов тела над ним: давка
		-- клиньями выжимает тела вверх, и без потолка куча у стены росла башней. Летящего
		-- от толчка потолок не держит.
		for b = 1, count do
			if not kin[b] then
				local base = (b - 1) * STRIDE
				for k = 1, n[b] do
					local i = base + k
					local floor = gr[i]
					if py[i] < floor then
						py[i] = floor
						supported[b] = true
					elseif not air[b] and climbV[b] <= 0 then
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
				-- На сколько ступни над полом: летящий над постройкой её не задевает.
				local above = math.huge
				for k = 1, nb do
					local i = base + k
					above = math.min(above, py[i] - gr[i])
				end
				local x, z = bound(user[b], cx, cz, ax, az, h, above)
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
			local fastest = 0
			for k = 1, nb do
				local i = base + k
				local x, y, z = (px[i] - ox[i]) / h, (py[i] - oy[i]) / h, (pz[i] - oz[i]) / h
				if y > maxRise and not air[b] then
					y = maxRise
				elseif y < -maxFall then
					y = -maxFall
				end
				-- С крыши по разрешению — не быстрее подъёма: так время перелезания совпадает
				-- с ценой лазания в поиске пути (вверх и вниз по высоте).
				local slow = climbV[b]
				if slow > 0 and not air[b] then
					if y < -slow then
						y = -slow
					end
					-- Сошёл с крыши и висит над полом без опоры — слезает по стене вниз, а не
					-- планирует вперёд: вбок не идёт, пока не встанет на пол.
					if not supported[b] and py[i] > gb[i] + 0.05 then
						x, z = 0, 0
					end
				end
				if perch[b] == GROUND and gr[i] > gb[i] + 0.05 and py[i] <= gr[i] + 0.05 then
					perch[b] = TOP
				end
				local speed = math.sqrt(x * x + z * z)
				if speed > maxSpeed then
					x, z = x / speed * maxSpeed, z / speed * maxSpeed
				end
				vx[i], vy[i], vz[i] = x, y, z
				if want > 1e-3 then
					along += (x * dvx + z * dvz) / want
				end
				fastest = math.max(fastest, x * x + y * y + z * z)
			end
			progress[b] = math.max(0, along / nb)
			if dead[b] then
				local rest = cfg.restSpeed
				if supported[b] and not air[b] and fastest < rest * rest then
					still[b] += h
				else
					still[b] = 0
				end
			end
		end
	end
end

-- Шаг на время кадра dt: кадр делится на равные подшаги не длиннее cfg.step, их не больше
-- cfg.maxSubsteps. Долг времени не копится: на просевшем сервере жуки идут медленнее,
-- а не рывками догоняют. Тело, которому с прошлого шага не дали привода, ведомое
-- (кроме трупа: он движется сам).
-- Возвращает число подшагов.
function CrowdSolver:step(dt)
	local cfg = self.cfg
	dt = math.min(dt, cfg.step * cfg.maxSubsteps)
	if dt <= 0 or self.count == 0 then
		return 0
	end
	local kin, fresh = self.kin, self.fresh
	local dead = self.dead
	for b = 1, self.count do
		if not fresh[b] and not dead[b] then
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
