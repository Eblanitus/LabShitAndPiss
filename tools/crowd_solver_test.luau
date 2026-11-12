-- Проверка решателя толпы на точках (src/ServerScriptService/CrowdSolver.luau) без Studio:
-- сцена из чисел — ровный пол, стена с дверью, жуки идут сквозь неё к цели.
--   tools/bin/lune run tools/crowd_solver_test
-- Ловит грубое: нечисловые значения, проходы сквозь стену, глубокие пересечения тел,
-- провал под пол, верхний не падает, когда нижнего убрали. Время шага — для порядка,
-- на сервере Roblox оно другое. Это не замена Play-теста.
local fs = require("@lune/fs")
local luau = require("@lune/luau")

-- Числа те же, что в игре: таблица crowd из PhysicsFX (файл возвращает таблицу без require).
-- Типы Roblox в таблице (Color3, Vector3...) подменяются пустышками: решателю нужны только числа.
local stub
stub = setmetatable({}, {
	__index = function()
		return stub
	end,
	__call = function()
		return stub
	end,
})
local physics = luau.load(fs.readFile("src/ReplicatedStorage/PhysicsFX.luau"), {
	environment = { Color3 = stub, Vector3 = stub, NumberRange = stub, NumberSequence = stub, Enum = stub },
})()
local CFG = physics.crowd
local CrowdSolver = luau.load(fs.readFile("src/ServerScriptService/CrowdSolver.luau"))()

local DT = 1 / 60
local failures = 0
local function check(ok, message)
	print((ok and "  ok   " or "  FAIL ") .. message)
	if not ok then
		failures += 1
	end
end

-- Стена поперёк z = 0 с дверью |x| < DOOR, арена |x| <= 20, |z| <= 40.
local DOOR = 3
local WALLS = {
	{ minX = -20, maxX = -DOOR, minZ = -0.5, maxZ = 0.5 },
	{ minX = DOOR, maxX = 20, minZ = -0.5, maxZ = 0.5 },
}
local RADIUS, FRONT, BACK, TOP, LIFT = 1.3, 1.2, -1.4, 0.8, 1.2

local function outOfRect(x, z, r, rect)
	local minX, maxX, minZ, maxZ = rect.minX - r, rect.maxX + r, rect.minZ - r, rect.maxZ + r
	if x <= minX or x >= maxX or z <= minZ or z >= maxZ then
		return x, z
	end
	local exits = { { x - minX, minX, nil }, { maxX - x, maxX, nil }, { z - minZ, nil, minZ }, { maxZ - z, nil, maxZ } }
	local best = exits[1]
	for _, e in exits do
		if e[1] < best[1] then
			best = e
		end
	end
	return best[2] or x, best[3] or z
end

local function newSolver()
	return CrowdSolver.new(CFG, {
		ground = function()
			return 0
		end,
		turnStep = function(angle, dt)
			return math.clamp(math.abs(angle) * 6, 2, 12) * dt
		end,
		-- Как в Crowd: по центру тела, капсула грубо — шаром по радиусу плюс половина длины.
		bound = function(user, x, z, fx, fz, h, above)
			x, z = math.clamp(x, -20, 20), math.clamp(z, -40, 40)
			-- Стена высотой 3: летящий выше неё перелетает (как постройки в Crowd).
			for _, rect in (above or 0) > 3 and {} or WALLS do
				-- Каждая точка хребта не в стене: сдвиг всего тела.
				for _, along in { FRONT, BACK } do
					local px, pz = x + fx * along, z + fz * along
					local nx, nz = outOfRect(px, pz, RADIUS, rect)
					x += nx - px
					z += nz - pz
				end
			end
			return x, z
		end,
	})
end

local function spawn(solver, x, z, fx, fz)
	local user = {}
	user.b = solver:add(user, x, LIFT, z, fx or 0, fz or 1, RADIUS, FRONT, BACK, TOP, LIFT, CFG.mass)
	return user
end

local function finite(v)
	return v == v and v > -1e6 and v < 1e6
end

-- Ход «как у маршрута»: к двери, за стеной — к цели. Привод — желаемая скорость.
local function steer(solver, user, speed)
	local x, _, z = solver:pivot(user.b)
	local tx, tz = 0, 30
	if z < -1 then
		tx, tz = 0, 1
	end
	local dx, dz = tx - x, tz - z
	local len = math.sqrt(dx * dx + dz * dz)
	if len < 0.3 then
		solver:drive(user.b, 0, 0)
		return
	end
	solver:drive(user.b, dx / len * speed, dz / len * speed, dx / len, dz / len)
end

-- Сколько точек в стене и насколько тела вошли друг в друга (доля суммы радиусов).
local function audit(solver)
	local inWall, deepest, nan, under = 0, 0, 0, 0
	local pts = {}
	for b = 1, solver.count do
		local n, point = solver:points(b)
		for k = 1, n do
			local x, y, z, r, hc, hs = point(k)
			if not (finite(x) and finite(y) and finite(z)) then
				nan += 1
			end
			if y < LIFT - 0.05 then
				under += 1
			end
			for _, rect in WALLS do
				if x > rect.minX and x < rect.maxX and z > rect.minZ and z < rect.maxZ then
					inWall += 1
				end
			end
			table.insert(pts, { b = b, x = x, y = y + hc, z = z, r = r, h = hs })
		end
	end
	for i = 1, #pts do
		local a = pts[i]
		for j = i + 1, #pts do
			local c = pts[j]
			if a.b ~= c.b then
				local R, H = a.r + c.r, a.h + c.h
				local q = math.sqrt(((a.x - c.x) ^ 2 + (a.z - c.z) ^ 2) / (R * R) + (a.y - c.y) ^ 2 / (H * H))
				deepest = math.max(deepest, 1 - q)
			end
		end
	end
	return inWall, deepest, nan, under
end

print("1. Одиночный жук: время пути против идеального")
do
	local solver = newSolver()
	local user = spawn(solver, 0, -20)
	local speed = 10
	local t = 0
	while t < 20 do
		steer(solver, user, speed)
		solver:step(DT)
		t += DT
		local _, _, z = solver:pivot(user.b)
		if z >= 20 then
			break
		end
	end
	local ideal = 40 / speed
	check(math.abs(t - ideal) / ideal <= 0.05, ("дошёл за %.2f с при идеале %.2f с (допуск 5%%)"):format(t, ideal))
	local _, y = solver:pivot(user.b)
	check(math.abs(y - LIFT) < 0.05, ("высота пивота %.2f, пол + lift = %.2f"):format(y, LIFT))
end

print("2. Толпа через дверь")
do
	local solver = newSolver()
	local users = {}
	for row = 0, 9 do
		for col = 0, 5 do
			table.insert(users, spawn(solver, -10 + col * 4 + (row % 2), -36 + row * 3.2))
		end
	end
	local passed, firstPass, lastPass = {}, nil, nil
	local worstWall, worstDeep, nanTotal, underTotal = 0, 0, 0, 0
	local maxY = 0
	local t = 0
	local spent, worstStep, steps = 0, 0, 0
	while t < 40 do
		for _, user in users do
			steer(solver, user, 8)
		end
		local started = os.clock()
		solver:step(DT)
		local s = os.clock() - started
		spent += s
		worstStep = math.max(worstStep, s)
		steps += 1
		t += DT
		for _, user in users do
			local _, y, z = solver:pivot(user.b)
			maxY = math.max(maxY, y)
			if z > 1 and not passed[user] then
				passed[user] = t
				firstPass = firstPass or t
				lastPass = t
			end
		end
		if steps % 30 == 0 then
			local inWall, deepest, nan, under = audit(solver)
			worstWall = math.max(worstWall, inWall)
			worstDeep = math.max(worstDeep, deepest)
			nanTotal += nan
			underTotal += under
		end
	end
	local count = 0
	for _ in passed do
		count += 1
	end
	check(nanTotal == 0, "нечисловых координат нет")
	check(worstWall == 0, ("точек в стене: %d"):format(worstWall))
	check(underTotal == 0, ("точек под полом: %d"):format(underTotal))
	check(worstDeep < 0.35, ("глубже всего тела вошли друг в друга на %.0f%% суммы радиусов"):format(worstDeep * 100))
	check(count == #users, ("прошли дверь %d из %d"):format(count, #users))
	if firstPass and lastPass and lastPass > firstPass then
		print(("       пропускная способность: %.1f жуков/с (с %.1f по %.1f с)"):format(
			(count - 1) / (lastPass - firstPass), firstPass, lastPass))
	end
	print(("       выше всех пивот поднимался до %.2f (пол + lift = %.2f): лезли на спины"):format(maxY, LIFT))
	print(("       шаг: в среднем %.3f мс, худший %.3f мс на %d тел (Lune, не Roblox)"):format(
		spent / steps * 1000, worstStep * 1000, #users))
end

print("3. Верхний падает, когда нижнего убрали")
do
	local solver = newSolver()
	local low = spawn(solver, 0, 10)
	local high = spawn(solver, 0, 10)
	-- Верхнего ставим на спину нижнему: ступни на верхе спины.
	solver:place(high.b, 0, LIFT + TOP + LIFT, 10, 0, 1)
	for _ = 1, 60 do
		solver:drive(low.b, 0, 0)
		solver:drive(high.b, 0, 0)
		solver:step(DT)
	end
	local _, yOn = solver:pivot(high.b)
	check(yOn > LIFT + 0.8, ("стоит на спине: пивот %.2f"):format(yOn))
	local moved = solver:remove(low.b)
	if moved then
		moved.b = low.b
	end
	for _ = 1, 60 do
		solver:drive(high.b, 0, 0)
		solver:step(DT)
	end
	local _, yDown = solver:pivot(high.b)
	check(math.abs(yDown - LIFT) < 0.1, ("упал на пол: пивот %.2f"):format(yDown))
end

print("4. Время шага на плотной куче")
for _, total in { 150, 300 } do
	local solver = newSolver()
	local users = {}
	local side = math.ceil(math.sqrt(total))
	for i = 0, total - 1 do
		table.insert(users, spawn(solver, -18 + (i % side) * 2.2, 2 + (i // side) * 2.2))
	end
	local spent, worst, steps = 0, 0, 0
	for frame = 1, 240 do
		for _, user in users do
			local x, _, z = solver:pivot(user.b)
			local dx, dz = -x, 30 - z
			local len = math.max(math.sqrt(dx * dx + dz * dz), 1e-3)
			solver:drive(user.b, dx / len * 8, dz / len * 8, dx / len, dz / len)
		end
		local started = os.clock()
		solver:step(DT)
		if frame > 60 then
			local s = os.clock() - started
			spent += s
			worst = math.max(worst, s)
			steps += 1
		end
	end
	local _, deepest, nan = audit(solver)
	check(nan == 0, ("%d тел: нечисловых нет, глубже всего %.0f%%"):format(total, deepest * 100))
	print(("       шаг: в среднем %.2f мс, худший %.2f мс (Lune, не Roblox)"):format(spent / steps * 1000, worst * 1000))
end

print("5. Толчок: одиночный жук проезжает те же studs (шаг 2, допуск 10%)")
for _, distance in { 0.5, 1, 3, 6, 10 } do
	local solver = newSolver()
	local user = spawn(solver, 0, -30)
	solver:drive(user.b, 0, 0)
	solver:step(DT)
	local x0, _, z0 = solver:pivot(user.b)
	solver:shove(user.b, 0, distance)
	local apex = 0
	for _ = 1, 240 do
		solver:drive(user.b, 0, 0)
		solver:step(DT)
		local _, y = solver:pivot(user.b)
		apex = math.max(apex, y - LIFT)
	end
	local x1, y1, z1 = solver:pivot(user.b)
	local moved = math.sqrt((x1 - x0) ^ 2 + (z1 - z0) ^ 2)
	check(math.abs(moved - distance) / distance <= 0.1 and math.abs(y1 - LIFT) < 0.05 and not solver:airborne(user.b),
		("толчок %.1f: проехал %.2f, взлетал на %.2f, сел"):format(distance, moved, apex))
end

print("6. Толчок в толпу: передний отлетает меньше, задних сдвигает")
do
	local solver = newSolver()
	local front = spawn(solver, 0, -20)
	local row = {}
	for i = 1, 5 do
		table.insert(row, spawn(solver, -4 + (i - 1) * 2.7, -20 + 3.2))
	end
	local function settle(frames)
		for _ = 1, frames do
			solver:drive(front.b, 0, 0)
			for _, u in row do
				solver:drive(u.b, 0, 0)
			end
			solver:step(DT)
		end
	end
	settle(10)
	local before = {}
	for _, u in row do
		local x, _, z = solver:pivot(u.b)
		before[u] = Vector3 and nil or { x, z }
		before[u] = { x, z }
	end
	local _, _, fz0 = solver:pivot(front.b)
	solver:shove(front.b, 0, 6)
	settle(240)
	local _, _, fz1 = solver:pivot(front.b)
	local shifted = 0
	for _, u in row do
		local x, _, z = solver:pivot(u.b)
		shifted += math.sqrt((x - before[u][1]) ^ 2 + (z - before[u][2]) ^ 2)
	end
	check(fz1 - fz0 < 6 and shifted > 0.5,
		("передний проехал %.2f из 6, задние сдвинулись в сумме на %.2f"):format(fz1 - fz0, shifted))
end

print("7. Подброс: дуга на высоту и посадка в цель")
do
	local solver = newSolver()
	local user = spawn(solver, -10, -30)
	solver:drive(user.b, 0, 0)
	solver:step(DT)
	local height, tx, tz = 10, 8, 10
	local x0, _, z0 = solver:pivot(user.b)
	local vx, up, vz = CrowdSolver.tossVelocity(CFG, tx - x0, tz - z0, height)
	local flight = 2 * up / CFG.gravity
	solver:knock(user.b, vx, up, vz, 0)
	local apex, t, landedAt = 0, 0, nil
	for _ = 1, 600 do
		solver:drive(user.b, 0, 0)
		solver:step(DT)
		t += DT
		local _, y = solver:pivot(user.b)
		apex = math.max(apex, y - LIFT)
		if not landedAt and t > CFG.tossLand and not solver:airborne(user.b) then
			landedAt = t
		end
	end
	local x1, y1, z1 = solver:pivot(user.b)
	local miss = math.sqrt((x1 - tx) ^ 2 + (z1 - tz) ^ 2)
	check(math.abs(apex - height) < 1 and miss < 1.5 and landedAt ~= nil and math.abs(y1 - LIFT) < 0.05,
		("вершина %.1f (надо %d), промах %.2f, сел через %.2f с (полёт %.2f)"):format(
			apex, height, miss, landedAt or -1, flight))
end

print("8. Кувырок: лёг на спину, полежал, встал и пошёл")
do
	local solver = newSolver()
	local user = spawn(solver, 0, -30)
	solver:drive(user.b, 0, 0)
	solver:step(DT)
	-- Вверх с таким креном, чтобы к посадке сделать пол-оборота: ляжет на спину.
	solver:knock(user.b, 0, 12, 0, math.pi / (2 * 12 / CFG.gravity))
	local maxRoll, onBackMoved, t, onBack = 0, 0, 0, 0
	local lastX, _, lastZ = solver:pivot(user.b)
	local stoodAt = nil
	for _ = 1, 360 do
		solver:drive(user.b, 0, 8, 0, 1)
		solver:step(DT)
		t += DT
		local roll = solver.roll[user.b]
		maxRoll = math.max(maxRoll, math.abs(roll))
		local x, _, z = solver:pivot(user.b)
		if not solver:airborne(user.b) and math.abs(roll) > math.pi / 2 then
			onBack += DT
			onBackMoved += math.sqrt((x - lastX) ^ 2 + (z - lastZ) ^ 2)
		end
		if not stoodAt and t > 0.5 and math.abs(roll) < 0.1 then
			stoodAt = t
		end
		lastX, lastZ = x, z
	end
	local _, _, z = solver:pivot(user.b)
	check(onBack >= CFG.flipTime and onBackMoved < 0.3 and stoodAt ~= nil and z > -25,
		("крен до %.1f рад, на спине %.2f с (надо от %.1f), прополз %.2f, встал через %.2f с, ушёл до z=%.1f"):format(
			maxRoll, onBack, CFG.flipTime, onBackMoved, stoodAt or -1, z))
	local lx, ly, lz, ux, uy, uz = solver:tilt(user.b)
	check(math.abs(lx * ux + ly * uy + lz * uz) < 1e-3 and uy > 0.99,
		("кадр после кувырка ровный: верх (%.2f, %.2f, %.2f)"):format(ux, uy, uz))
end

print("9. Грызущий тяжелее: толпа его почти не сдвигает")
do
	local function pushed(heavy)
		local solver = newSolver()
		local chewer = spawn(solver, 0, 20)
		local crowd = {}
		for i = 1, 6 do
			table.insert(crowd, spawn(solver, -6 + i * 2.2, 14 - (i % 2) * 2.5))
		end
		local x0, _, z0 = solver:pivot(chewer.b)
		for _ = 1, 120 do
			solver:drive(chewer.b, 0, 0, 0, 1, heavy)
			for _, u in crowd do
				local x, _, z = solver:pivot(u.b)
				local dx, dz = -x, 20 - z
				local len = math.max(math.sqrt(dx * dx + dz * dz), 1e-3)
				solver:drive(u.b, dx / len * 8, dz / len * 8, dx / len, dz / len)
			end
			solver:step(DT)
		end
		local x1, _, z1 = solver:pivot(chewer.b)
		return math.sqrt((x1 - x0) ^ 2 + (z1 - z0) ^ 2)
	end
	local light, heavy = pushed(1), pushed(CFG.holdMass)
	check(heavy < light, ("обычного сдвинули на %.2f, грызущего на %.2f"):format(light, heavy))
end

-- ============ Шаг 3: карта стен, постройки, лазание ============

-- Карта расстояний до прямоугольных стен (как запекает Crowd, только точно).
local function makeField(walls, x0, z0, x1, z1)
	local w, hgt = x1 - x0 + 1, z1 - z0 + 1
	local data = table.create(w * hgt, 0)
	for row = 0, hgt - 1 do
		for col = 0, w - 1 do
			local x, z = x0 + col, z0 + row
			local best = math.huge
			for _, rect in walls do
				local dx = math.max(rect.minX - x, 0, x - rect.maxX)
				local dz = math.max(rect.minZ - z, 0, z - rect.maxZ)
				local d
				if dx == 0 and dz == 0 then
					d = -math.min(x - rect.minX, rect.maxX - x, z - rect.minZ, rect.maxZ - z)
				else
					d = math.sqrt(dx * dx + dz * dz)
				end
				best = math.min(best, d)
			end
			data[row * w + col + 1] = best
		end
	end
	return { x0 = x0, z0 = z0, w = w, h = hgt, cell = 1, data = data }
end

local function boxSolver()
	return CrowdSolver.new(CFG, {
		ground = function()
			return 0
		end,
		turnStep = function(angle, dt)
			return math.clamp(math.abs(angle) * 6, 2, 12) * dt
		end,
		bound = function(user, x, z)
			return math.clamp(x, -30, 30), math.clamp(z, -40, 40)
		end,
	})
end

local function walkTo(solver, user, tx, tz, speed)
	local x, _, z = solver:pivot(user.b)
	local dx, dz = tx - x, tz - z
	local len = math.sqrt(dx * dx + dz * dz)
	if len < 0.2 then
		solver:drive(user.b, 0, 0)
	else
		solver:drive(user.b, dx / len * speed, dz / len * speed, dx / len, dz / len)
	end
end

print("10. Стены картой расстояний: толпа в дверь, точек в стене нет")
do
	local solver = boxSolver()
	solver:setField(makeField(WALLS, -35, -45, 35, 45))
	local users = {}
	for row = 0, 5 do
		for col = 0, 5 do
			table.insert(users, spawn(solver, -10 + col * 4, -30 + row * 3.2))
		end
	end
	local worst, passed = 0, 0
	for frame = 1, 1800 do
		for _, user in users do
			steer(solver, user, 8)
		end
		solver:step(DT)
		if frame % 10 == 0 then
			for b = 1, solver.count do
				local n, point = solver:points(b)
				for k = 1, n do
					local x, _, z = point(k)
					local d = solver:wallDistance(x, z)
					if d and d < 0 then
						worst = math.max(worst, -d)
					end
				end
			end
		end
	end
	for _, user in users do
		local _, _, z = solver:pivot(user.b)
		if z > 1 then
			passed += 1
		end
	end
	check(worst == 0, ("глубже всего точка в стене: %.2f studs"):format(worst))
	check(passed == #users, ("прошли дверь %d из %d"):format(passed, #users))
end

-- Постройка: квадрат 4 x 4 высотой 2 поперёк пути.
local BOX = { minX = -2, maxX = 2, minZ = -2, maxZ = 2, top = 2, gap = 0 }

print("11. Постройка: кто лезть не может, тот не входит и не встаёт сверху")
do
	local solver = boxSolver()
	solver:setBoxes({ BOX })
	local user = spawn(solver, 0, -10)
	local inside, onTop = 0, 0
	for _ = 1, 600 do
		walkTo(solver, user, 0, 10, 8)
		solver:step(DT)
		local n, point = solver:points(user.b)
		for k = 1, n do
			local x, y, z = point(k)
			if x > BOX.minX + 0.5 and x < BOX.maxX - 0.5 and z > BOX.minZ + 0.5 and z < BOX.maxZ - 0.5 then
				inside += 1
				if y - LIFT >= BOX.top - 0.1 then
					onTop += 1
				end
			end
		end
	end
	local _, _, z = solver:pivot(user.b)
	check(inside == 0 and onTop == 0, ("точек в следе: %d, на крыше: %d; встал у стены z=%.1f"):format(inside, onTop, z))
end

print("12. Перелезание телом: по разрешению, время против расчёта поиска пути (план: 10%, здесь 20%)")
for _, case in { { speed = 1.2, height = 2 }, { speed = 3, height = 2 }, { speed = 1, height = 4 } } do
	local solver = boxSolver()
	local box = table.clone(BOX)
	box.top = case.height
	solver:setBoxes({ box })
	local user = spawn(solver, 0, -6)
	solver:allowClimb(user.b, case.speed, case.height + 0.5)
	local walk = 8
	local t, startedAt, doneAt, maxFeet, wall = 0, nil, nil, 0, false
	for _ = 1, 60 * 30 do
		walkTo(solver, user, 0, 12, walk)
		solver:step(DT)
		t += DT
		local x, y, z = solver:pivot(user.b)
		maxFeet = math.max(maxFeet, y - LIFT)
		if solver:perchOf(user.b) == CrowdSolver.WALL then
			wall = true
			startedAt = startedAt or t
		end
		if startedAt and not doneAt and z > box.maxZ + RADIUS and solver:perchOf(user.b) == CrowdSolver.GROUND
			and y - LIFT < 0.05 then
			doneAt = t
		end
	end
	-- Расчёт как у перелезания по таймеру: вверх и вниз по высоте со скоростью подъёма,
	-- поперёк крыши — шагом (ширина следа плюс длина тела).
	local expected = 2 * case.height / case.speed + (box.maxZ - box.minZ + (FRONT - BACK)) / walk
	local took = doneAt and startedAt and doneAt - startedAt
	check(wall and took ~= nil and math.abs(took - expected) / expected <= 0.2 and maxFeet >= case.height - 0.1,
		("скорость %.1f, высота %d: перелез за %.2f с, расчёт %.2f с, ступни поднимались до %.2f"):format(
			case.speed, case.height, took or -1, expected, maxFeet))
end

print("13. По спинам через постройку не перелезть, если лезть нельзя")
do
	local solver = boxSolver()
	local wallBox = { minX = -40, maxX = 40, minZ = -1, maxZ = 1, top = 1.6, gap = 0 }
	solver:setBoxes({ wallBox })
	local users = {}
	for row = 0, 5 do
		for col = 0, 7 do
			table.insert(users, spawn(solver, -10 + col * 2.8, -16 + row * 2.8))
		end
	end
	local crossed, onTop = 0, 0
	for frame = 1, 1200 do
		for _, user in users do
			walkTo(solver, user, 0, 20, 8)
		end
		solver:step(DT)
		if frame % 10 == 0 then
			for b = 1, solver.count do
				local n, point = solver:points(b)
				for k = 1, n do
					local x, y, z = point(k)
					if z > wallBox.minZ + 0.3 and z < wallBox.maxZ - 0.3 then
						onTop += 1
					end
				end
			end
		end
	end
	for _, user in users do
		local _, _, z = solver:pivot(user.b)
		if z > wallBox.maxZ then
			crossed += 1
		end
	end
	check(crossed == 0 and onTop == 0, ("перелезли: %d, точек над стеной: %d"):format(crossed, onTop))
end

print("14. Подлаз: тело ниже щели проходит под постройкой")
do
	local solver = boxSolver()
	local low = table.clone(BOX)
	low.gap = TOP + LIFT + 0.5
	solver:setBoxes({ low })
	local user = spawn(solver, 0, -10)
	for _ = 1, 300 do
		walkTo(solver, user, 0, 10, 8)
		solver:step(DT)
	end
	local _, _, z = solver:pivot(user.b)
	check(z > 9, ("прошёл под постройкой до z=%.1f"):format(z))
end

print("15. Труп: убитый в полёте летит дальше, ложится, точка покоя как у живого (шаг 4)")
do
	local function fly(kill)
		local solver = newSolver()
		local user = spawn(solver, 0, -30)
		solver:drive(user.b, 0, 0)
		solver:step(DT)
		local x0, _, z0 = solver:pivot(user.b)
		solver:shove(user.b, 0, 6)
		local restedAt, speedAtKill = nil, 0
		for frame = 1, 300 do
			if frame == 6 and kill then
				local vx, vy, vz = solver:velocity(user.b)
				speedAtKill = math.sqrt(vx * vx + vy * vy + vz * vz)
				solver:kill(user.b)
			end
			if not (kill and frame >= 6) then
				solver:drive(user.b, 0, 0)
			end
			solver:step(DT)
			if kill and not restedAt and solver:resting(user.b) then
				restedAt = frame * DT
			end
		end
		local x1, y1, z1 = solver:pivot(user.b)
		return math.sqrt((x1 - x0) ^ 2 + (z1 - z0) ^ 2), y1, restedAt, speedAtKill
	end
	local alive = fly(false)
	local dead, y, restedAt, speed = fly(true)
	check(speed > 5, ("в момент смерти тело летит со скоростью %.1f studs/с"):format(speed))
	check(math.abs(dead - alive) <= 0.15 * alive and math.abs(y - LIFT) < 0.05,
		("труп проехал %.2f, живой %.2f, лежит на полу"):format(dead, alive))
	check(restedAt ~= nil and restedAt < 2.5, ("лёг через %.2f с"):format(restedAt or -1))
end

print("16. Труп — помеха живым: его отталкивают, живой проходит")
do
	local solver = newSolver()
	local corpse = spawn(solver, 0, 10)
	solver:drive(corpse.b, 0, 0)
	solver:step(DT)
	solver:kill(corpse.b)
	local walker = spawn(solver, 0.3, 2)
	local deepest = 0
	for _ = 1, 360 do
		local x, _, z = solver:pivot(walker.b)
		local dx, dz = 0 - x, 20 - z
		local len = math.max(math.sqrt(dx * dx + dz * dz), 1e-3)
		solver:drive(walker.b, dx / len * 6, dz / len * 6, dx / len, dz / len)
		solver:step(DT)
		local _, d = audit(solver)
		deepest = math.max(deepest, d)
	end
	local cx, cy, cz = solver:pivot(corpse.b)
	local _, _, wz = solver:pivot(walker.b)
	local shifted = math.sqrt(cx * cx + (cz - 10) ^ 2)
	check(wz > 18, ("живой прошёл до z=%.1f"):format(wz))
	check(shifted > 0.3 and math.abs(cy - LIFT) < 0.6, ("труп сдвинули на %.2f, пивот %.2f"):format(shifted, cy))
	check(deepest < 0.35, ("глубже всего вошли друг в друга на %.0f%%"):format(deepest * 100))
	check(solver:resting(corpse.b), "после этого труп лежит")
end

print(failures == 0 and "Всё прошло." or ("Провалов: %d"):format(failures))
if failures > 0 then
	error("crowd solver test failed")
end
