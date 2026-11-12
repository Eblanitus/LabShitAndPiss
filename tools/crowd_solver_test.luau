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
		bound = function(user, x, z, fx, fz, h)
			x, z = math.clamp(x, -20, 20), math.clamp(z, -40, 40)
			for _, rect in WALLS do
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

print(failures == 0 and "Всё прошло." or ("Провалов: %d"):format(failures))
if failures > 0 then
	error("crowd solver test failed")
end
