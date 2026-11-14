-- Бак стола (по вики экономики v1.1): алхимический стол и крафтит, и перерабатывает. Сверху
-- алхимия, под столешницей бак с бурлящей жидкостью, который переваривает жуков. Отдельного
-- реактора нет. Сюда приходят останки, которые привезли носильщики (Carriers), и через
-- Economy.processTime становятся материей. Стол разбит — бак не работает: потерял стол —
-- потерял и крафт, и доход.
--
-- Точки подключения для интерфейса и картинки:
--   * Remotes.EconomyFX:FireAllClients("load", стол, value) — груз сброшен в бак;
--   * Remotes.EconomyFX:FireAllClients("processed", стол, amount) — переработка кончилась,
--     amount материи ушло в кошелёк (целое, может быть 0 — копится дробная часть);
--   * атрибут Processing (число) на модели стола — сколько грузов сейчас в баке
--     (бурление бака — клиент TableVat).
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerScriptService = game:GetService("ServerScriptService")

local Economy = require(ReplicatedStorage:WaitForChild("Economy"))
local Matter = require(ServerScriptService:WaitForChild("Matter"))
local Corpses = require(ServerScriptService:WaitForChild("Corpses"))
local LabTable = require(ServerScriptService:WaitForChild("LabTable"))
local EconomyFX = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild("EconomyFX")

local TableDigest = {}

-- Дробная материя: клочья Мини-жука стоят 0.6, и без накопления такие грузы пропадали бы целиком.
local carry = 0
-- Поколение забега: переработка, начатая до рестарта, в новый забег материю не приносит.
local generation = 0

local function bump(model, delta)
	if model and model.Parent then
		model:SetAttribute("Processing", math.max((model:GetAttribute("Processing") or 0) + delta, 0))
	end
end

-- Груз сброшен в бак: через processTime его ценность станет материей.
-- Возвращает false, если бак не принял груз (стол разбит).
function TableDigest.Process(value)
	if value <= 0 then
		return true
	end
	if not LabTable.IsAlive() then
		return false
	end
	local mine = generation
	local model = LabTable.Model()
	bump(model, 1)
	EconomyFX:FireAllClients("load", model, value)
	task.delay(Economy.processTime, function()
		if mine ~= generation then
			return
		end
		bump(model, -1)
		-- Стол разгрызли, пока груз варился: материя пропала вместе с баком.
		if not LabTable.IsAlive() then
			return
		end
		carry += value
		local whole = math.floor(carry + 1e-6)
		carry -= whole
		if whole > 0 then
			Matter.Add(whole)
		end
		EconomyFX:FireAllClients("processed", model, whole)
	end)
	return true
end

-- Новый забег: недоработанное и дробный остаток сгорают вместе с прежним забегом.
function TableDigest.Reset()
	generation += 1
	carry = 0
	local model = LabTable.Model()
	if model then
		model:SetAttribute("Processing", 0)
	end
end

-- Сбор без носильщиков (Economy.autoCollectDelay): труп сам уходит в бак через
-- заданное время после смерти. Остался для проверок, по умолчанию выключен.
task.spawn(function()
	while true do
		task.wait(0.5)
		local delay = Economy.autoCollectDelay
		if delay then
			local now = os.clock()
			for _, record in Corpses.Valuable() do
				if now - record.bornAt >= delay then
					TableDigest.Process(Corpses.Take(record))
				end
			end
		end
	end
end)

return TableDigest
