-- Дроны-носильщики на клиенте: кузов и колёса. Сервер ставит только атрибут Loaded на дроне
-- (Carriers) и двигает дрона целиком; гонять CFrame каждой детали с сервера значило бы
-- реплицировать их каждый кадр ради картинки (тот же довод, что у BuildingVisuals).
-- Дрон сдал груз в бак стола (Loaded стал false) — кузов опрокидывается и опускается обратно.
-- Бурление бака под столом — TableVat.client.
local RunService = game:GetService("RunService")
local Workspace = game:GetService("Workspace")

local carriersFolder = Workspace:WaitForChild("Carriers")

local TIP_TIME = 0.5 -- сек на подъём кузова
local TIP_HOLD = 1.1 -- сек от сдачи груза до команды «опустить»
local WAIT_ANCHOR = 15

local drones = {} -- [model] = { root, hinge, hingeBase, tip, wheels = { { joint, base, angle, radius } }, last }

local function attachDrone(model)
	if drones[model] or not model:IsA("Model") then
		return
	end
	task.spawn(function()
		local root = model:WaitForChild("Root", WAIT_ANCHOR)
		local hinge = root and root:WaitForChild("BinHinge", WAIT_ANCHOR)
		if not hinge or not model.Parent then
			return
		end
		local entry = {
			root = root,
			hinge = hinge,
			hingeBase = hinge.C0,
			tipAngle = math.rad(hinge:GetAttribute("TipAngle") or 45),
			tip = 0,
			tipUntil = 0,
			loaded = model:GetAttribute("Loaded") == true,
			wheels = {},
			last = root.Position,
		}
		local function addWheel(joint)
			if joint:IsA("Motor6D") and joint.Name == "WheelJoint" then
				table.insert(entry.wheels, { joint = joint, base = joint.C0, angle = 0, radius = joint:GetAttribute("Radius") or 0.8 })
			end
		end
		for _, joint in root:GetChildren() do
			addWheel(joint)
		end
		root.ChildAdded:Connect(addWheel)
		drones[model] = entry
	end)
end

local function smooth(t)
	return t * t * (3 - 2 * t)
end

RunService.RenderStepped:Connect(function(dt)
	local now = os.clock()
	for model, entry in drones do
		if not model.Parent or not entry.root.Parent then
			drones[model] = nil
		else
			-- Кузов: груз сдан — поднимается, держится и опускается обратно.
			local loaded = model:GetAttribute("Loaded") == true
			if entry.loaded and not loaded then
				entry.tipUntil = now + TIP_HOLD
			end
			entry.loaded = loaded
			local want = now < entry.tipUntil and 1 or 0
			if entry.tip ~= want then
				local step = dt / TIP_TIME
				entry.tip = want > entry.tip and math.min(entry.tip + step, 1) or math.max(entry.tip - step, 0)
				entry.hinge.C0 = entry.hingeBase * CFrame.Angles(entry.tipAngle * smooth(entry.tip), 0, 0)
			end
			-- Колёса крутятся по пройденному пути (вперёд — по LookVector, назад — обратно).
			local position = entry.root.Position
			local moved = (position - entry.last):Dot(entry.root.CFrame.LookVector)
			entry.last = position
			if math.abs(moved) > 1e-4 then
				for _, wheel in entry.wheels do
					wheel.angle = (wheel.angle + moved / wheel.radius) % (2 * math.pi)
					wheel.joint.C0 = wheel.base * CFrame.Angles(wheel.angle, 0, 0)
				end
			end
		end
	end
end)

for _, model in carriersFolder:GetChildren() do
	attachDrone(model)
end
carriersFolder.ChildAdded:Connect(attachDrone)
