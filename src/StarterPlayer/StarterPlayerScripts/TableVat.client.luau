-- Бак под столешницей алхимического стола (по вики экономики v1.1): сверху алхимия, снизу
-- бурлящая жидкость, которая переваривает жуков. Чисто картинка и только на клиенте: сервер
-- ставит на модели стола атрибут Processing (сколько грузов в баке, TableDigest), здесь бак
-- от него бурлит сильнее и светится ярче. Разбит стол (HP = 0) — бак гаснет.
--
-- Бак строится из примитивов под столешницей: стеклянная ванна и светящаяся жидкость с
-- пузырями. Коллизии у него нет и не нужно: он внутри габарита стола, а стол уже твёрдый.
-- Размер — от габарита стола (Arena.tableHalf) и высоты столешницы (деталь Top).
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Arena = require(ReplicatedStorage:WaitForChild("Arena"))

local GLASS = Color3.fromRGB(70, 110, 120)
local LIQUID = Color3.fromRGB(80, 235, 175) -- тот же зелёный биомассы, что у дронов (CarrierRig)
local IDLE_RATE = 3 -- пузырей в секунду, пока бак пуст
local BUSY_RATE = 28 -- пока что-то варится
local IDLE_LIGHT = 0.6
local BUSY_LIGHT = 2.2

local vat = nil -- { model, table, liquid, emitter, light, baseY, phase, heat }

local function part(parent, name, size, cframe, color, material, transparency)
	local p = Instance.new("Part")
	p.Name = name
	p.Size = size
	p.CFrame = cframe
	p.Color = color
	p.Material = material
	p.Transparency = transparency
	p.Anchored = true
	p.CanCollide = false
	p.CanQuery = false
	p.CanTouch = false
	p.CastShadow = false
	p.TopSurface = Enum.SurfaceType.Smooth
	p.BottomSurface = Enum.SurfaceType.Smooth
	p.Parent = parent
	return p
end

local function clear()
	if vat and vat.model.Parent then
		vat.model:Destroy()
	end
	vat = nil
end

local function build()
	clear()
	local location = Arena.Location()
	local craftTable = location and location:WaitForChild("CraftTable", 15)
	local top = craftTable and craftTable:WaitForChild("Top", 15)
	local half = Arena.tableHalf
	if not (top and half and half.X > 0 and half.Z > 0) then
		return
	end

	local centre = craftTable:GetPivot().Position
	local floorY = Arena.floorY
	local underside = top.Position.Y - top.Size.Y / 2
	local room = underside - floorY
	if room < 0.8 then
		return -- под столешницей места нет: бак не влезет
	end

	-- Ванна — на полу между ножками, чуть ниже половины высоты под столешницей.
	local height = math.max(room * 0.5, 0.6)
	local sizeX, sizeZ = half.X * 2 * 0.62, half.Z * 2 * 0.55
	local model = Instance.new("Model")
	model.Name = "Vat"
	part(model, "Tank", Vector3.new(sizeX, height, sizeZ),
		CFrame.new(centre.X, floorY + height / 2, centre.Z), GLASS, Enum.Material.Glass, 0.65)
	local liquidHeight = height * 0.78
	local liquid = part(model, "Liquid", Vector3.new(sizeX - 0.2, liquidHeight, sizeZ - 0.2),
		CFrame.new(centre.X, floorY + 0.05 + liquidHeight / 2, centre.Z), LIQUID, Enum.Material.Neon, 0.3)

	local emitter = Instance.new("ParticleEmitter")
	emitter.Name = "Bubbles"
	emitter.EmissionDirection = Enum.NormalId.Top
	emitter.Shape = Enum.ParticleEmitterShape.Box
	emitter.ShapeStyle = Enum.ParticleEmitterShapeStyle.Volume
	emitter.Rate = IDLE_RATE
	emitter.Lifetime = NumberRange.new(0.5, 1.0)
	emitter.Speed = NumberRange.new(0.6, 1.6)
	emitter.SpreadAngle = Vector2.new(15, 15)
	emitter.Size = NumberSequence.new({
		NumberSequenceKeypoint.new(0, 0.12),
		NumberSequenceKeypoint.new(0.8, 0.28),
		NumberSequenceKeypoint.new(1, 0),
	})
	emitter.Transparency = NumberSequence.new(0.2, 1)
	emitter.Color = ColorSequence.new(LIQUID)
	emitter.LightEmission = 0.7
	emitter.Parent = liquid

	local light = Instance.new("PointLight")
	light.Color = LIQUID
	light.Range = math.max(sizeX, sizeZ) * 1.2
	light.Brightness = IDLE_LIGHT
	light.Shadows = false
	light.Parent = liquid

	model.Parent = craftTable
	vat = {
		model = model,
		table = craftTable,
		liquid = liquid,
		emitter = emitter,
		light = light,
		baseCF = liquid.CFrame,
		phase = 0,
		heat = 0,
	}
end

RunService.RenderStepped:Connect(function(dt)
	if not vat then
		return
	end
	if not vat.model.Parent or not vat.table.Parent then
		vat = nil
		return
	end
	local alive = (vat.table:GetAttribute("HP") or 1) > 0
	for _, p in vat.model:GetChildren() do
		if p:IsA("BasePart") then
			p.LocalTransparencyModifier = alive and 0 or 1
		end
	end
	vat.emitter.Enabled = alive
	vat.light.Enabled = alive
	if not alive then
		return
	end

	-- heat плавно идёт к 1, пока в баке что-то варится, и остывает к 0, когда пусто.
	local busy = (vat.table:GetAttribute("Processing") or 0) > 0
	local target = busy and 1 or 0
	vat.heat += (target - vat.heat) * math.min(dt * 3, 1)
	vat.emitter.Rate = IDLE_RATE + (BUSY_RATE - IDLE_RATE) * vat.heat
	vat.light.Brightness = IDLE_LIGHT + (BUSY_LIGHT - IDLE_LIGHT) * vat.heat

	-- Поверхность ходит вверх-вниз: в покое едва, на переваривании — заметно.
	vat.phase = (vat.phase + dt * (2 + 6 * vat.heat)) % (2 * math.pi)
	local bob = math.sin(vat.phase) * (0.02 + 0.06 * vat.heat)
	vat.liquid.CFrame = vat.baseCF + Vector3.new(0, bob, 0)
end)

task.spawn(build)
Arena.OnChanged(function()
	task.spawn(build)
end)
