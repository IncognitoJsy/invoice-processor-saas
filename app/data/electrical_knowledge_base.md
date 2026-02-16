# GoZappify Electrical Knowledge Base
## Voice-to-Quote AI Reference Document v1.0

---

# 1. PURPOSE

This document is the AI's reference for parsing voice transcriptions into structured electrical installation quotes. It contains the default rules, product mappings, and trade knowledge that an experienced UK electrician would apply automatically. The AI must apply these rules unless the transcription explicitly states otherwise.

---

# 2. CIRCUIT DESIGN DEFAULTS

## 2.1 Socket Circuits

| Rule | Default | Override Trigger |
|------|---------|-----------------|
| Socket circuit type | **Ring main** | User says "radial", "spur only", or specifies radial |
| Ring main cable | **2.5mm² Twin & Earth (T&E)** | — |
| Ring main protection | **32A MCB (Type B)** | User specifies Type C or RCD |
| Ring main max floor area | **100m²** per circuit (BS 7671) | — |
| Radial cable (20A) | **2.5mm² T&E** | — |
| Radial cable (32A) | **4.0mm² T&E** | — |
| Dedicated socket circuits | Kitchen sockets on own circuit, ring or radial | User specifies |
| FCU / Fused Spur | **13A fused connection unit** unless load specified | User states amp rating |
| USB sockets | Treat as standard socket for circuit purposes, different part number | — |

## 2.2 Lighting Circuits

| Rule | Default | Override Trigger |
|------|---------|-----------------|
| Lighting cable | **1.5mm² T&E** | — |
| Lighting protection | **6A MCB (Type B)** | User specifies |
| Max points per circuit | **12 points** (recommended, not regulatory max) | — |
| Downlights / spots | **Fire-rated LED** fittings assumed | User says "non-fire-rated" or "surface mount" |
| Lamp type for downlights | **Integrated LED or GU10 LED** depending on fitting | User specifies |
| 2-way switching cable | **1.5mm² 3-Core & Earth** between switch positions | — |
| Intermediate switching | **1.5mm² 3-Core & Earth** to intermediate switch | User says "3-way" or "intermediate" |
| Dimmer circuits | LED compatible dimmer assumed, trailing edge | User specifies leading edge |
| Bathroom lighting | IP rated as per zones (see Section 6) | — |
| External lighting | IP65 minimum, consider photocell/PIR | User specifies |

## 2.3 Underfloor Heating

### Wet vs Electric Detection

**CRITICAL RULE:** The thermostat model tells you whether it's wet or electric UFH:
- **NeoStat-E** (with "E") = **Electric** UFH → mat, adhesive, foil tape, dedicated circuit, floor probe
- **ANY other NeoStat model** (NeoStat, NeoStat v2, Neo v2, etc.) = **Wet** UFH → thermostat ONLY, no mat, no adhesive, no tape

If the user just says "NeoStat" or "Neo" without specifying "E", default to **WET** underfloor heating.

### NeoStat Back Box
All NeoStat thermostats require a **single (1-gang) back box** at the mounting position.

### Electric UFH (NeoStat-E)

| Rule | Default |
|------|---------|
| UFH mat sizing | **User provides exact heated floor area** — do NOT estimate or deduct for furniture |
| Thermostat | **Heatmiser NeoStat-E** (default for electric) |
| Thermostat back box | **1-gang back box** (35mm metal flush or SB631 dry lining) |
| Thermostat cable | Run from mat location to stat position |
| Floor probe | Included with thermostat, embedded in mat area |
| Mat adhesive | **Spray adhesive** — 1 can covers **4m² maximum** |
| Mat tape | **Aluminium foil tape** to secure mat edges and joins |
| Protection | Dedicated circuit, 30mA RCD protected (RCBO) |
| Cable size | **2.5mm² T&E** (up to 15A mat) or **4.0mm² T&E** if higher load |
| RCBO | **16A Type B** (standard domestic mat) — check mat wattage |
| Floor prep / insulation boards | **Done by main contractor** — do NOT include unless user specifies |
| Floor probe conduit | Flag if tiled floor — probe may need conduit for future replacement |

### Wet UFH (NeoStat / NeoStat v2 / Neo v2)

| Rule | Default |
|------|---------|
| Thermostat | **Heatmiser NeoStat v2** (or model stated) |
| Thermostat back box | **1-gang back box** (35mm metal flush or SB631 dry lining) |
| Thermostat cable | Run from thermostat to actuator/manifold |
| **NO mat** | Wet system — heating is in the screed, not an electric mat |
| **NO adhesive spray** | Not applicable |
| **NO foil tape** | Not applicable |
| **NO dedicated circuit** | Thermostat is low voltage control only |

### Spray Adhesive Calculation (Electric UFH Only)
**CRITICAL: Always round UP to whole cans. You cannot buy half cans.**
- 1 can = 4m² coverage
- 6m² floor → 6 ÷ 4 = 1.5 → **round up to 2 cans**
- 12m² floor → 12 ÷ 4 = 3.0 → **3 cans**
- 15m² floor → 15 ÷ 4 = 3.75 → **round up to 4 cans**
- This rounding rule applies to ALL consumables — anything sold in whole units must round up

**AI behaviour:** When user mentions "underfloor heating" or "UFH", first determine WET or ELECTRIC from the thermostat model. If NeoStat-E → electric, include mat, adhesive, tape, probe, dedicated circuit. If any other NeoStat → wet, include thermostat and cable to manifold ONLY.

## 2.4 Dedicated Circuits

### kW Input Required
For cookers, hobs, showers, EV chargers, and other high-load appliances, the AI **must request or use the kW rating** from the user to determine correct cable size and RCBO rating. If not provided, flag for confirmation.

### Cable Sizing — Rough Calculation
The AI should perform a basic cable sizing check:
- **Current (A)** = kW × 1000 ÷ Voltage (230V single phase, 400V three phase)
- Select cable size with current-carrying capacity ≥ circuit current (accounting for installation method)
- This is a **rough approximation** — flag: "Cable sizing is estimated. Confirm with full design calculation considering installation method, grouping, insulation, and ambient temperature."

### Circuit Defaults

| Appliance | Cable | Protection | Notes |
|-----------|-------|------------|-------|
| Cooker | **6.0mm² T&E** (up to ~13kW) | 32A RCBO | Via 45A cooker switch with neon. **Deeper back box needed** (35mm min) due to cable size |
| Hob (induction) | **6.0mm² or 10mm² T&E** | 32A or 40A RCBO | **User must provide kW rating** |
| Oven (built-in) | **2.5mm² T&E** | 20A RCBO | Via FCU or 20A DP switch |
| Electric shower | **See kW table below** | See table | **User must provide kW rating** |
| Immersion heater | **2.5mm² T&E** | 16A RCBO | Via 20A DP switch |
| EV charger | **See kW table below** | See table | **User must provide charger kW rating**. Requires own circuit, PEN fault protection |
| Smoke / heat detection | **1.5mm² T&E** | **Dedicated 6A RCBO** | Always dedicated circuit, interlinked, mains with battery backup |
| Outdoor socket | **2.5mm² T&E** | 20A RCBO | IP66 rated socket |
| Towel rail | **1.5mm² T&E** | Via FCU (3A fuse) | Fused connection unit |
| Extractor fan | **1.5mm² T&E** | Wired to lighting switch circuit | Default: **Envirovent SIL100T** (built-in run-on timer). Always include fan isolator |

### Extractor Fan Rules

**Default product:** Envirovent SIL100T (timer model with built-in run-on timer)

**Wiring:** Extractor fans are ALWAYS wired to the room's lighting switch so they trigger ON when the lights are activated. The fan's built-in run-on timer keeps it running after lights are turned off.

**Fan isolator:** Every extractor fan requires a fan isolator switch and a single (1-gang) back box.
- Hager Sollysta white plastic: **WMPS3PIF** (3-pole fan isolator)
- The isolator is mounted near the fan (typically just outside the room or above the door)

**Per fan, always include:**
| Qty | Product | Part No. |
|-----|---------|----------|
| 1 | Envirovent SIL100T extractor fan | SIL100T |
| 1 | Hager 3-pole fan isolator | WMPS3PIF |
| 1 | 1-gang back box (for isolator) | Per wall type |

### Shower kW to Cable Sizing
| Shower Rating | Current (A) | Minimum Cable | RCBO |
|--------------|-------------|---------------|------|
| 7.5kW | 32.6A | 6.0mm² T&E | 40A Type B |
| 8.5kW | 37.0A | 6.0mm² or 10mm² T&E | 40A Type B |
| 9.5kW | 41.3A | 10mm² T&E | 45A Type B |
| 10.5kW | 45.7A | 10mm² T&E | 45A or 50A Type B |

### EV Charger kW to Cable Sizing
| Charger Rating | Current (A) | Minimum Cable | RCBO |
|---------------|-------------|---------------|------|
| 3.6kW (single phase) | 16A | 2.5mm² T&E | 20A Type B |
| 7.4kW (single phase) | 32A | 6.0mm² T&E or SWA | 32A Type B/C |
| 22kW (three phase) | 32A per phase | 6.0mm² 5-core SWA | 32A Type B/C (3-phase) |

**Note on deep back boxes:** Cooker isolators, 45A switches, and any accessory fed by 6mm² or larger cable should use **35mm or 47mm deep back boxes** to accommodate the cable bulk. AI must automatically select deeper boxes for these accessories.

### Wall-Mounted Electric Radiators / Heaters (Default: Rointe Kyros)

**Default brand:** Rointe Kyros (RAD4 generation — Wi-Fi enabled, inverter smart adaptive)

When user mentions "heater" / "radiator" / "wall heater" / "electric rad" / "panel heater", default to Rointe Kyros RAD4 unless a specific model is stated.

### Kyros RAD4 Standard Range (3 sizes — White)

| Part Number | Wattage | Elements | Width | Room Size |
|-------------|---------|----------|-------|-----------|
| **KRIW0600RAD4** | 600W | 4 | 430mm | Up to **9m²** |
| **KRIW1200RAD4** | 1200W | 8 | 720mm | **9m² to 18m²** |
| **KRIW1800RAD4** | 1800W | 12 | 1010mm | **18m² and above** (up to ~25m²) |

All standard Kyros: **580mm height × 95mm depth**. Wall bracket mounted (120mm from wall).
Jersey has a mild climate — Rointe classifies it as such. These sizing cutoffs reflect practical experience.

### Kyros RAD4 Short / Conservatory Range (White)

| Part Number | Wattage | Elements | Width | Room Size |
|-------------|---------|----------|-------|-----------|
| **KRIW1000RADC4** | 1000W | 8 | 720mm | Up to ~10m² |
| **KRIW1250RADC4** | 1250W | 10 | 900mm | Up to ~12m² |
| **KRIW1500RADC4** | 1500W | 12 | 1050mm | Up to ~15m² |

Short range: **420mm height** — for low-level walls, under windows, conservatories.

### Room Size Calculation

The AI must select the correct radiator size based on room dimensions:

**Step 1:** Calculate room floor area: **Length × Width = m²**
**Step 2:** Apply ceiling height factor:
- Standard ceiling (2.4m): × 1.0 (no adjustment)
- High ceiling (2.7-3.0m): × 1.15
- Very high ceiling (3.0-3.5m): × 1.25
- Vaulted ceiling: × 1.5

**Step 3:** Apply room type factor:
- Bedroom / living room (well insulated): × 1.0
- Kitchen / utility (more heat loss): × 1.1
- Conservatory / extension (poor insulation): × 1.3

**Step 4:** Result = adjusted m². Select radiator from table where room size coverage ≥ adjusted m².

**Example:** Room is 4m × 5m = 20m², needs a heater → **KRIW1800RAD4** (20m² is above 18m² cutoff)
**Example:** Room is 3m × 4m = 12m², needs a heater → **KRIW1200RAD4** (12m² is within 9-18m² range)
**Example:** Room is 3m × 6m = 18m², needs a heater → **KRIW1200RAD4** (18m² is the boundary — stays with 1200W)
**Example:** Room is 2.5m × 3m = 7.5m², needs a heater → **KRIW0600RAD4** (under 9m²)

### Electrical Requirements per Radiator

| Item | Requirement |
|------|-------------|
| Circuit | Dedicated spur or ring main socket (single radiator ≤ 13A can be on ring) |
| Connection | Hardwired via flex outlet or fused connection unit |
| Cable | 2.5mm² T&E (up to 1800W = 7.8A) |
| Back box | 1-gang back box for flex outlet / FCU — per wall type |

**AI behaviour for radiators:**
1. When "heater" or "radiator" is mentioned, check if room dimensions are available
2. Calculate room area and select appropriate Kyros RAD4 model
3. If room dimensions not provided, flag: "Room dimensions needed to size radiator correctly"
4. If a specific Rointe model is mentioned (not Kyros), use that model exactly
5. Each radiator needs a connection point — include flex outlet or FCU + back box in materials
6. For multiple radiators in one room, each needs its own connection point
7. Matt black variants available — if user says "black heater" / "black radiator", use the RAL 9005 matt black variant (same part number structure, different colour code)

## 2.5 Consumer Unit

### Default Manufacturer: Hager

| Rule | Default |
|------|---------|
| CU manufacturer | **Hager** (single phase and 3-phase) |
| Circuit protection | **RCBO per circuit** (not split-load MCB + RCD) |
| Single phase RCBO | **6kA rated** |
| Three phase RCBO | **10kA rated** |
| Main switch (single phase) | **100A** (unless specified otherwise) |
| Three phase incomer | **Hager incomer kit** — 100A default (or as specified: 63A, 80A, 125A) |
| Surge protection | **SPD Type 2** required — **MAIN BOARD ONLY** (sub-boards do NOT need SPD) |
| Meter tails | **25mm² T&E** (standard domestic single phase) |
| CU sizing | Count total circuits + **25% spare ways** for future use (minimum 2 spare ways) |
| Blanking modules | 1 per spare way |

### Single Phase Board
- Hager RCBO board (e.g., Design 10 or Design 30 range)
- 1× RCBO per circuit (6kA rated)
- 100A main switch
- SPD Type 2
- Sized to number of circuits + spare ways

### Three Phase Board
- Hager 3-phase distribution board
- 1× incomer kit (100A default, user specifies if different)
- 1× RCBO per circuit (10kA rated)
- SPD Type 2 (3-phase rated)
- Phase balancing: AI should flag "Ensure circuits are balanced across phases"
- Metering: flag if separate metering per phase required

### Sub-Distribution Boards
- Sub-boards (e.g., garage, outbuilding, extension) do **NOT** need surge protection — SPD is on main board only
- Sub-boards still need RCBO per circuit
- Fed via SWA or T&E from main board (sized to total load)
- Own main switch required
- Earth arrangement: check TT vs TN-C-S — if TT earth at outbuilding, sub-board needs own RCD arrangement

### When to Use Three Phase
The AI should recognise these triggers in transcription:
- "Three phase" / "3-phase" / "3 phase supply"
- "415 volt" / "415V"
- Large commercial or industrial load
- Multiple EV chargers
- Large kitchen (commercial)
- Workshop with 3-phase machinery

### RCBO Selection Logic
| Circuit Type | RCBO Rating | Sensitivity | kA Rating |
|-------------|-------------|-------------|-----------|
| Lighting | 6A Type B | 30mA | 6kA (1ph) / 10kA (3ph) |
| Sockets (ring) | 32A Type B | 30mA | 6kA / 10kA |
| Sockets (radial 20A) | 20A Type B | 30mA | 6kA / 10kA |
| Cooker | 32A Type B | 30mA | 6kA / 10kA |
| Shower | 40A or 50A Type B | 30mA | 6kA / 10kA |
| EV Charger | 32A Type B or C | 30mA (Type A or B RCD element) | 6kA / 10kA |
| Smoke detection | 6A Type B | 30mA | 6kA / 10kA |
| UFH | 16A Type B | 30mA | 6kA / 10kA |
| Immersion | 16A Type B | 30mA | 6kA / 10kA |
| Outbuilding (SWA) | Sized to load | 30mA (or TT = 100mA + 30mA at sub) | 6kA / 10kA |

**AI behaviour:** Always default to RCBO per circuit. Never suggest split-load MCB + RCD boards unless the user explicitly asks for a budget option. If budget is mentioned, flag: "Split-load board available as cost saving — confirm if preferred over RCBO board."

---

# 3. WALL TYPES & BACK BOX SELECTION

## 3.1 Wall Type Detection

The AI must listen for these terms in the transcription:

| Transcription Term | Wall Type | Interpretation |
|-------------------|-----------|----------------|
| "studwork" / "stud walls" / "stud" / "timber frame" | Plasterboard on timber studs | Dry lining boxes |
| "dot and dab" / "dabs" / "dry lined" | Plasterboard on dabs against blockwork | **Metal flush boxes** (solid wall behind plasterboard) |
| "solid walls" / "brick" / "block" / "masonry" / "concrete" | Solid construction | Metal flush boxes, chased in |
| "back to brick" / "chasing" / "chase out" | Solid walls being chased | Metal flush boxes |
| "noggins" / "timber backing" / "noggined out" | Studwork with timber backing behind plasterboard | Metal flush boxes (screwed to noggin) |
| "surface mount" / "surface" / "mounted on surface" | Any wall, surface installation | Surface mount (pattress) boxes |
| "trunking" / "mini trunking" / "dado trunking" | Surface containment system | Trunking adaptable boxes |

## 3.2 Back Box Mapping

### Plasterboard / Dry Lining (Studwork, Dot & Dab)

| Accessory Type | Back Box | Example Part No. | Notes |
|---------------|----------|-------------------|-------|
| Single gang socket / switch | **35mm single dry lining box** | SB631 | Fast-fix / spring-loaded lugs |
| Double gang socket | **35mm dual dry lining box** | SB629 | Fast-fix / spring-loaded lugs |
| Dimmer (single gang) | **35mm single dry lining box** | SB631 | Check dimmer depth requirement |
| Deep dimmer / fan controller | **47mm single dry lining box** | SB633 | For deeper accessories |
| Cooker switch | **35mm dual dry lining box** | SB629 | — |
| Fused spur / FCU | **35mm single dry lining box** | SB631 | — |
| Shaver socket | **35mm single dry lining box** | SB631 | — |
| Data / TV outlet | **35mm single dry lining box** | SB631 | — |

### Solid Walls (Brick, Block, Masonry) or Noggins

**Default depth: 35mm. NEVER use 25mm as default.**
If user says "deep boxes" → use **47mm**.

| Accessory Type | Back Box | Notes |
|---------------|----------|-------|
| Single gang socket / switch | **35mm 1-gang metal flush box** | With adjustable lugs |
| Double gang socket | **35mm 2-gang metal flush box** | With adjustable lugs |
| Dimmer (single gang) | **47mm 1-gang metal flush box** | Deeper for dimmer module |
| Deep dimmer / fan controller | **47mm 1-gang metal flush box** | — |
| Cooker switch | **47mm 2-gang metal flush box** | Deeper due to cable size (6mm²+) |

### Surface Mount

| Accessory Type | Back Box | Notes |
|---------------|----------|-------|
| Single gang | **16mm or 25mm surface pattress box** | White plastic |
| Double gang | **16mm or 25mm surface pattress box** | White plastic |

## 3.3 Key Rules

- If wall type is NOT mentioned, **ask user / flag as ambiguous** — do not assume
- If "throughout" is mentioned with a wall type, apply to ALL rooms in the entire job unless a specific room overrides
- If wall type is stated for a specific room only, it applies to that room alone
- **Default metal box depth is 35mm** — never default to 25mm
- If user says "deep" or "deep boxes" → use **47mm**
- **User should specify back box depth** (35mm or 47mm) — if not specified, default to 35mm
- Back box depth must accommodate the accessory — dimmers and fan controllers typically need 47mm depth
- **Accessories fed by 6mm² or larger cable** (cooker isolators, shower switches) must use **35mm or 47mm deep boxes** regardless of user default
- Earth terminal in every metal back box — include earth sleeving in materials
- Dry lining boxes do NOT need earth connection (plastic)
- **All accessories should conform to Building Regs Part M heights**: sockets 450mm FFL to bottom of box, switches 1200mm FFL to top of box
- All similar accessories (FCUs, isolators, data points, TV points) should follow the same height guidance

## 3.4 Cable Drops & Containment

For first-fix wiring on studwork, cables dropping from ceiling void to back box positions need mechanical protection:

| Item | Default | Notes |
|------|---------|-------|
| Cable drop protection | **Oval conduit / slip tube** | From ceiling void to each back box position |
| Conduit length per drop | **Height from ceiling to box** (calculated from room height and box height) |
| Socket drops | Ceiling height minus 450mm (socket height from FFL) |
| Switch drops | Room height minus 1200mm (switch height from FFL) |

**AI behaviour:** For every accessory on studwork walls, calculate one cable drop using oval conduit. Include the oval conduit length in the materials list. For solid walls (chased), conduit is not required for drops — capping may be used instead.

---

# 4. FINISH & PRODUCT RANGE MAPPING

## 4.1 Finish Vocabulary

The AI must recognise these terms and map to the correct finish category:

| Transcription Terms | Finish Category |
|--------------------|-----------------|
| "white" / "white plastic" / "PVC" / "standard" / "budget" / "basic" | **White Moulded** |
| "brushed chrome" / "BC" / "chrome" / "satin chrome" | **Brushed Chrome** |
| "polished chrome" / "mirror chrome" / "shiny chrome" | **Polished Chrome** |
| "matt black" / "black" / "black nickel" / "anthracite" | **Matt Black** |
| "satin brass" / "brushed brass" / "brass" / "gold" | **Satin Brass** |
| "stainless steel" / "stainless" / "SS" | **Stainless Steel** |
| "screwless" / "flat plate" / "no screws showing" / "frameless" | **Screwless** (style modifier) |
| "screwed" / "traditional" / "showing screws" / "standard plate" | **Screwed** (style modifier) |

## 4.2 Insert Colour

The insert is the inner plastic part — rocker switches, plug aperture surrounds, module fronts.

| Transcription Terms | Insert Colour |
|--------------------|---------------|
| "white insert" / "white inserts" / "white inners" | **White** |
| "black insert" / "black inserts" / "black inners" | **Black** |
| Not mentioned | **Use range default** (see 4.3) |

## 4.3 Default Brand/Range Mapping

These are the USER'S default preferences. Each user configures their own. Below are the system defaults:

| Finish Category | Style | Default Range | Default Insert | Notes |
|----------------|-------|---------------|----------------|-------|
| White Moulded | Screwed | **Hager Sollysta** | White | Budget/standard option |
| Brushed Chrome | Screwed | **Hamilton 74 Series** | White (default) | Can be black insert |
| Brushed Chrome | Screwless | **Configurable** | Black (typical) | User sets preferred range |
| Polished Chrome | Screwed | **Configurable** | White (default) | — |
| Matt Black | Screwless | **Configurable** | Black | — |
| Satin Brass | Screwed | **Configurable** | White or Black | — |

## 4.4 Context Inheritance Rules

- If a finish is stated once for a job (e.g., "Hamilton 74 throughout, brushed chrome, black inserts"), it applies to ALL accessories in ALL rooms unless overridden
- If a finish is stated for a room (e.g., "brushed chrome in the master"), it applies to all accessories in that room
- If a different finish is stated for a specific room (e.g., "but white plastic in the utility"), only that room changes
- Dimmers, blanking plates, cooker switches, fused spurs, shaver sockets, TV outlets — ALL follow the room's finish setting
- Grid plates: the grid frame and modules must match the insert colour

## 4.5 Euro Module System (Data / TV / Telephone Consolidation)

**CRITICAL: The AI must NEVER spec individual face plates for data, TV, telephone, and satellite points.** These are consolidated onto euro module front plates with individual euro modules slotted in.

### How It Works
Instead of 4 separate face plates for 2× data + 1× TV + 1× telephone, you use:
- Multi-module front plates (available in 2, 4, 6 module sizes)
- Individual euro modules that snap into the plate
- Blank modules to fill unused slots

### Hager Sollysta Euro Module Parts

**Front Plates:**
| Part Number | Description |
|-------------|-------------|
| **WMP2EU** | 2-module euro front plate (single gang size) |
| **WMP4EU** | 4-module euro front plate (double gang size) |

**Euro Modules:**
| Part Number | Description |
|-------------|-------------|
| **WMMRJ45** | RJ45 data / internet euro module |
| **WMMQX** | TV / satellite coax euro module |
| **WMMBTM** | BT telephone master euro module |
| **WMMB** | Blank euro module (fills unused slot) |

### AI Behaviour for Data/TV/Telephone
1. Count total data, TV, telephone, and satellite points in the room
2. Group onto the minimum number of euro plates needed
3. Fill any empty slots with WMMB blank modules
4. Each plate needs a back box: WMP2EU → single back box (SB631), WMP4EU → dual back box (SB629)

**Example — Bedroom with 2× data, 1× TV/SAT, 1× telephone:**
- 1× WMP4EU (4-module plate) + 2× WMMRJ45 + 1× WMMQX + 1× WMMB → on SB629
- 1× WMP2EU (2-module plate) + 1× WMMBTM + 1× WMMB → on SB631

## 4.6 Hager Grid System (Switches)

### When to Use Grid
Grid is used when multiple switch modules are needed at one position — instead of a multi-gang standard plate, you use a grid plate + frame + individual grid switch modules. This allows mixing different module types (2-way, intermediate, retractive, dimmers) on one plate.

### Grid Components

**Frames — Universal 3/4 Gang:**
| Part Number | Description |
|-------------|-------------|
| **WMGF34** | Grid frame — fits BOTH 3-gang and 4-gang front plates (one product, two uses) |

**Front Plates:**
| Part Number | Description | Back Box Required |
|-------------|-------------|-------------------|
| **WMGP3** | 3-gang grid front plate | **2-gang (twin) back box** |
| **WMGP4** | 4-gang grid front plate | **2-gang (twin) back box** |

**CRITICAL: 3-gang and 4-gang grid plates require a TWIN (2-gang) back box, NOT a single.**

**Grid Switch Modules:**
| Part Number | Description | Use |
|-------------|-------------|-----|
| **WMGS12** | Grid 2-way switch module | Standard 2-way switching positions |
| **WMGS16** | Grid intermediate switch module | Middle position in 3-way (or more) switching |

### Assembly Rule
- Always 1× front plate + 1× WMGF34 frame + correct number of grid modules
- The WMGF34 frame is the SAME part number whether used with a 3-gang or 4-gang plate
- Module count must match the gang count of the front plate

### AI Behaviour for Grid
When a switching position has 3 or more circuits, or needs a mix of switch types, use the grid system:
- Determine number of circuits at the position → select WMGP3 or WMGP4
- Always add 1× WMGF34 frame
- Select correct module type per circuit (WMGS12 for 2-way, WMGS16 for intermediate)

## 4.7 Hager Dimmer Plate System

**CRITICAL: Dimmer positions use a COMPLETELY DIFFERENT system from the standard grid. Do NOT mix them up.**

### Dimmer Plate Kits
| Part Number | Description | Back Box Required |
|-------------|-------------|-------------------|
| **WMDRP1KIT** | 1-gang dimmer plate kit (1 hole) | 1-gang back box |
| **WMDRP2KIT** | 2-gang dimmer plate kit (2 holes) | 2-gang (twin) back box |
| **WMDRP3KIT** | 3-gang dimmer plate kit (3 holes) | **2-gang (twin) back box** |
| **WMDRP4KIT** | 4-gang dimmer plate kit (4 holes) | **2-gang (twin) back box** |

**CRITICAL: 3-gang and 4-gang dimmer plates require a TWIN (2-gang) back box, NOT a single.**

### Dimmer Modules
| Part Number | Description | Manufacturer |
|-------------|-------------|-------------|
| **DM298** | Grid dimmer module (LED compatible, rotary) | Collingwood |
| **IDPSWH** | Push on/off switch (looks like dimmer knob but is just a switch) | — |

### Assembly Rule
- 1× WMDRPXKIT (plate kit sized to number of dimmers/switches)
- Populate each position with either DM298 (for dimming) or IDPSWH (for on/off only)
- These are NOT interchangeable with WMGP/WMGF34 grid system

### AI Behaviour — Grid vs Dimmer Decision
| Position has... | System to use |
|----------------|---------------|
| Standard switches only (2-way, intermediate) | **Grid system** (WMGP + WMGF34 + WMGS modules) |
| Dimmers only or dimmers + push switches | **Dimmer plate system** (WMDRPXKIT + DM298/IDPSWH) |
| Mix of dimmers AND standard switches | **Two separate plates** at the position, or use grid system with compatible dimmer modules if available |

## 4.8 Product Resolution

When the AI has determined: **Range + Finish + Insert Colour + Accessory Type + Gang Count**, it searches the product database golden records by these attributes to find the specific part number.

If no exact match is found in the database, the AI should:
1. List the accessory with the best description it can (e.g., "Hamilton 74 BC 2G Switched Socket Black Insert")
2. Flag it for user to confirm the part number
3. Mark confidence as LOW

# 5. LIGHTING PRODUCTS

## 5.1 Downlights (Default: Collingwood)

### Default Product
The default downlight for all residential jobs is the **Collingwood DLT388** series — specifically the **DLT5515000** which is the colour AND wattage switchable variant. This is the go-to unless a specific colour temperature is requested.

### Part Number Logic — Collingwood DLT388 / DLT551 Series
The AI must understand the Collingwood naming convention to build the correct SKU:

| Part Number Segment | Meaning | Options |
|-------------------|---------|---------|
| DLT388 | Range (fire-rated, IP65, dimmable) | Fixed colour temp models |
| DLT5515000 | **Colour & wattage switchable** variant | **DEFAULT CHOICE** |
| **MW** | **Matt White** bezel | MW = Matt White, BC = Brushed Chrome, BS = Brushed Steel, MB = Matt Black |
| **55** | Wattage (5.5W) | May vary by model |
| **30** | 3000K (Warm White) | 30 = 3000K, 40 = 4000K |

**Examples of fixed colour temp models:**
- DLT388MW5530 = Matt White, 5.5W, Warm White (3000K)
- DLT388MW5540 = Matt White, 5.5W, Cool White (4000K)
- DLT388BS5530 = Brushed Steel, 5.5W, Warm White

### Default Selection Rules

| Scenario | Default Product |
|----------|----------------|
| User says "spots" / "downlights" / "spot lights" with no other detail | **DLT5515000** (colour & wattage switchable) **Matt White bezel** |
| User says "warm white spots" | DLT388MW5530 (Matt White, 3000K) |
| User says "cool white spots" | DLT388MW5540 (Matt White, 4000K) |
| User specifies "chrome bezels" | Switch to BC (Brushed Chrome) variant |
| User says "match the room" for bezel | Match bezel to room's accessory finish |
| Bathroom spots | Same default BUT must be fire-rated AND IP65 (DLT388/DLT551 is both) |
| Kitchen spots | Same default, check quantity for adequate coverage |
| **Utility room** | **Default to spots** unless user specifies LED battens or panels |

### Bezel Finish Default
**Matt White is ALWAYS the default** regardless of room finish, unless the user specifically requests matching bezels. This is because most ceilings are white and matt white bezels blend in.

### Coverage Rule of Thumb
- **Spot spacing: 1.6m to 1.8m apart maximum** — closer than this looks awful, too far apart creates dark spots
- Spots should be at least 600mm from walls
- AI should NOT calculate spot count automatically — use the quantity the user states
- If user says "fill the ceiling" or "loads of spots" — flag for exact count

### Associated Products per Downlight
Each downlight automatically adds:
- 1× fire-rated downlight cover/hood (if insulated ceiling above — flag to confirm)
- Cable connection via Wago or loop-in connector (included in sundries)

## 5.2 LED Strip Tape (Default: FOSS)

### Default Brand
**FOSS** is the default LED strip tape brand. When user mentions LED tape without specifying a brand, default to FOSS.

### When Referenced
User says "LED tape" / "LED strip" / "strip lighting" / "LED ribbon" / "cove lighting" / "under cabinet LED"

### What's Needed
LED strip tape requires TWO main components:
1. **LED tape** — sold per metre, various wattages per metre
2. **LED driver** — dimmable, wattage rated to match total tape load

### Driver Sizing Calculation
**CRITICAL: Driver wattage must exceed total tape wattage. Always round UP to next available driver size.**

Formula: **Total wattage = tape wattage per metre × total length in metres**
Then select a driver with wattage **≥ total wattage** (ideally 10-20% headroom).

| Example | Calculation | Driver Needed |
|---------|-------------|---------------|
| 10W/m tape, 8m run | 10 × 8 = 80W | **100W dimmable driver** |
| 10W/m tape, 18m run | 10 × 18 = 180W | **200W dimmable driver** |
| 14W/m tape, 5m run | 14 × 5 = 70W | **75W or 100W dimmable driver** |
| 20W/m tape, 3m run | 20 × 3 = 60W | **75W dimmable driver** |

### AI Behaviour for LED Tape
- User must provide: **wattage per metre** and **total run length**
- If not provided, flag: "Please confirm LED tape wattage per metre and total length required"
- AI calculates total wattage and selects appropriate driver
- Include in materials: tape (length in metres), driver (with wattage), connection accessories
- If tape run exceeds maximum single-run length for the product (typically 5m), flag: "Long run — may need multiple feeds or amplifiers"
- LED tape fed via FCU or dedicated switch
- Dimmable driver required if on a dimmer circuit

## 5.3 Other Lighting Types

### Pendant / Lampholder Positions
| Transcription Terms | Product | Notes |
|--------------------|---------|-------|
| "pendant" / "ceiling rose" / "pendant drop" | **Hager WPS6** ceiling rose + **B22 LED lamp (7.5-8W)** | Default pendant setup |
| "chandelier point" / "hook plate" / "ceiling hook" | **Ceiling rose or hook plate rated for weight** | Flag: "Confirm max weight of fitting for fixing type" |
| "customer supplies light" / "just wire to position" / "just a feed" / "client buying fittings" | **Wire to position only** — NO ceiling rose, NO lamp | Just cable to ceiling point |

**AI behaviour:** 
- Default pendant = Hager WPS6 + B22 LED lamp (7.5-8W)
- If customer is supplying their own fitting → wire to position ONLY, do not include WPS6 or lamp
- Always confirm: "Is the client purchasing their own light fittings for this room?"

### LED Battens
| Transcription Terms | Default Use | Notes |
|--------------------|-------------|-------|
| "LED batten" / "strip light" / "fluorescent" (replace) | **LED batten fitting** | Utility rooms, garages, workshops |
| "garage light" / "utility light" | **LED batten** unless spots specified | Standard 4ft (1200mm) or 5ft (1500mm) |

### LED Panels
| Transcription Terms | Default Use | Notes |
|--------------------|-------------|-------|
| "LED panel" / "panel light" / "office light" | **600×600mm LED panel** (recessed or surface mount) | Primarily commercial/office use |
| Residential use | Rare — only if user specifically mentions | More common in garages, home offices |

### Wall Lights / Sconces
| Transcription Terms | Product | Notes |
|--------------------|---------|-------|
| "wall light" / "sconce" / "wall fitting" | **Wire to position + back box** | Customer usually supplies fitting |
| "up/down lights" / "up and down" | **Wire to position** | External or internal feature lighting |

**AI behaviour:** Wall lights are almost always customer-supplied. Include wiring to position, suitable back box, and switch. Flag: "Customer supplying wall light fitting."

### External Lighting
| Transcription Terms | Product | Notes |
|--------------------|---------|-------|
| "security light" / "PIR flood" / "floodlight" | **LED PIR floodlight** | IP65 minimum, check wattage |
| "outside light" / "porch light" / "door light" | **External wall light** (often customer supplied) | IP44 minimum, with or without PIR |
| "garden light" / "bollard" / "spike light" | **Low voltage or mains garden lighting** | Flag: "Confirm if mains or 12V system" |
| "dusk to dawn" / "photocell" | **Fitting with built-in photocell** or separate photocell | Auto on/off with daylight |

### In-Ground / Floor-Recessed Lights
| Transcription Terms | Default Product | Notes |
|--------------------|----------------|-------|
| "in-ground" / "floor light" / "ground flood" / "floor recessed" | **Collingwood GLO19** (warm white flood) | Check IP rating for location |

**Collingwood GLO19:** In-ground LED flood light, warm white. Used for feature lighting in bathrooms (floor-recessed), hallways, external paths, and driveways. **IP68 rated** (continuous submersion) — suitable for ALL bathroom zones including Zone 0.

**AI behaviour for in-ground lights in bathrooms:**
- Collingwood in-ground lights are IP68 — they exceed requirements for all zones
- No IP rating flag needed for Collingwood in-ground products
- Still flag if a non-Collingwood in-ground light is specified (unknown IP rating)

## 5.4 Bathroom & Towel Rail Accessories

### Heated Towel Rail Connection
| Transcription Terms | Product | Part No. | Back Box |
|--------------------|---------|----------|----------|
| "towel rail" / "heated towel rail" / "towel warmer" | **Hager flex outlet plate** | **WMP2FO** | 1-gang back box (per wall type) |

**AI behaviour:** Heated towel rails are connected via a flex outlet plate, NOT a fused spur/FCU (unless user specifies FCU). The flex outlet provides a neat connection point for the towel rail's flex cable.
- Always include: 1× WMP2FO + 1× appropriate 1-gang back box
- The towel rail itself is usually client-supplied — wire to position with flex outlet

### Shaver Socket
| Transcription Terms | Product | Back Box |
|--------------------|---------|----------|
| "shaver socket" / "shaver point" / "razor socket" | **Hager Sollysta shaver socket** (BS EN 61558-2-5 isolating transformer type) | **47mm deep** back box (metal flush or dry lining) |

**CRITICAL: Shaver sockets ALWAYS need a 47mm DEEP back box** due to the built-in isolating transformer. This applies regardless of wall type.
- Permitted in bathroom Zone 2 and outside zones
- NOT permitted in Zone 0 or Zone 1
- Must be isolating transformer type (BS EN 61558-2-5) — this is the only type permitted in bathrooms

### Mirror Light Position
| Transcription Terms | Product | Notes |
|--------------------|---------|-------|
| "mirror light" / "mirror cabinet light" / "vanity light" | **Wire to position only** | Almost always client-supplied with the mirror/cabinet |
| "illuminated mirror" / "LED mirror" | **Fused connection unit or flex outlet at position** | Mirror plugs in or is hardwired |

**AI behaviour:** Mirror lights in bathrooms are nearly always supplied by the client (with the mirror unit). Include wiring to position only. Check zone compliance for the connection point.

---

# 6. CABLE TYPES & SIZING

## 6.1 Cable Types — Full Reference

The AI must understand all cable types a sparky might reference:

### Twin & Earth (T&E) — Flat Grey Cable
Standard cable for most domestic fixed wiring.

| Size | Common Uses | Protection |
|------|-------------|------------|
| **1.0mm²** | Lighting (short runs), doorbells, signalling | 6A MCB |
| **1.5mm²** | Lighting circuits, extractor fans, heated towel rails | 6A MCB |
| **2.5mm²** | Socket ring mains, radials (20A), immersion, UFH | 20A or 32A MCB |
| **4.0mm²** | Radial (32A), high-load sockets, small cookers | 32A MCB |
| **6.0mm²** | Cooker, hob, electric shower (up to 9kW), EV charger | 32A-40A MCB |
| **10.0mm²** | High-power shower (10.5kW+), large EV charger, sub-main | 40A-50A MCB |
| **16.0mm²** | Sub-mains, large loads | 63A MCB |
| **25.0mm²** | Meter tails (standard domestic) | Main switch 100A |

### 3-Core & Earth
| Size | Common Uses |
|------|-------------|
| **1.5mm²** | 2-way switching, intermediate switching, extract fan with timer |

### Singles (PVC Insulated)
Run in conduit or trunking — not clipped direct.

| Size | Common Uses |
|------|-------------|
| **1.5mm²** | Lighting in conduit systems |
| **2.5mm²** | Sockets in conduit systems |
| **4.0mm²** | Higher load circuits in conduit |
| **6.0mm²** | Sub-circuits in conduit |
| **10.0mm²** | Sub-mains in conduit |
| **16.0mm²** | Main distribution in conduit |
| **Earths** | Separate CPC (circuit protective conductor) required — green/yellow |

### Tough Sheath (SWA Alternative for Internal)
| Size | Common Uses |
|------|-------------|
| Various | Used where additional mechanical protection needed without full SWA |

### Steel Wire Armoured (SWA)
For external, underground, or where mechanical protection required.

**Single Phase (3-core: L, N, E)**
| Size | Common Uses |
|------|-------------|
| **2.5mm² 3-core** | External lighting circuits |
| **4.0mm² 3-core** | Outbuildings, garden rooms, external sockets |
| **6.0mm² 3-core** | Garage supply, workshop, EV charger (external run) |
| **10.0mm² 3-core** | Large outbuilding, sub-main to garage |
| **16.0mm² 3-core** | Heavy sub-main |
| **25.0mm² 3-core** | Large sub-main supply |

**Three Phase (5-core: L1, L2, L3, N, E)**
| Size | Common Uses |
|------|-------------|
| **2.5mm² 5-core** | Small 3-phase loads |
| **4.0mm² 5-core** | 3-phase motors, pumps |
| **6.0mm² 5-core** | 3-phase machinery, workshop supply |
| **10.0mm² 5-core** | Large 3-phase sub-main |
| **16.0mm² 5-core** | Heavy 3-phase distribution |
| **25.0mm² 5-core** | Main 3-phase supply |

**AI behaviour for SWA:** User must specify the size and whether single or three phase. For three phase loads (pumps, motors, machinery), default to **5-core SWA** (3 phases + neutral + earth). Always flag: "Confirm SWA size — user to specify 'x'mm 3-core or 5-core."

**SWA always needs:** glands (indoor + outdoor), gland plates, earth tags, adaptable boxes at each end.

### Bonding Cable
| Type | Size | Use |
|------|------|-----|
| **Main bonding** | **10.0mm² single green/yellow** | Gas, water, oil at point of entry |
| **Supplementary bonding** | **4.0mm² single green/yellow** | Bathroom — extraneous metalwork to earth |
| **Cross bonding** | **4.0mm² or 6.0mm²** | Between services where required |

**AI behaviour:** If the job is a full rewire, automatically include main bonding to gas and water in the materials list. If bathrooms are involved, include supplementary bonding. Flag: "Confirm bonding requirements on site."

## 6.2 MCB Types & Sizing

### MCB Types
| Type | Use |
|------|-----|
| **Type B** | Standard domestic — lighting, sockets, general circuits |
| **Type C** | Motor loads — air conditioning, commercial equipment, some EV chargers |
| **Type D** | High inrush — transformers, large motors (rarely domestic) |

### Common Domestic Circuit Schedule (RCBO Default)
| Circuit | RCBO Rating | Type | Cable |
|---------|-----------|----------|-------|
| Lighting | 6A | B | 1.5mm² T&E |
| Sockets (ring) | 32A | B | 2.5mm² T&E |
| Sockets (radial 20A) | 20A | B | 2.5mm² T&E |
| Sockets (radial 32A) | 32A | B | 4.0mm² T&E |
| Cooker | 32A | B | 6.0mm² T&E |
| Shower (≤9kW) | 40A | B | 6.0mm² T&E |
| Shower (>9kW) | 40A or 50A | B | 10.0mm² T&E |
| Immersion | 16A | B | 2.5mm² T&E |
| UFH (standard mat) | 16A | B | 2.5mm² T&E |
| EV Charger | 32A | B or C | 6.0mm² T&E or SWA |
| Smoke detection | 6A | B | 1.5mm² T&E |
| Outbuilding supply | Varies | B | SWA sized to load |

All RCBOs 30mA sensitivity, 6kA rated (single phase) or 10kA rated (three phase). See Section 2.5 for full consumer unit specification.

### RCBO as Standard
RCBO per circuit is the **GoZappify default** — every circuit gets individual RCD protection. This eliminates nuisance tripping affecting other circuits and is the professional standard for quality installations. Hager RCBOs used throughout (6kA single phase, 10kA three phase).

---

# 7. CABLE ESTIMATION

## 7.1 Circuit Continuity Between Rooms

**IMPORTANT:** Not every room has a dedicated run back to the consumer unit. Circuits often continue from one room into the next (e.g., a ring main serving multiple bedrooms, a lighting circuit covering a whole floor).

When the user does NOT specify a distance to the board, or says the circuit "continues into another room":
- Calculate cable for the room ONLY (perimeter runs, drops, internal routing)
- Do NOT add a "to board" run
- Leave cable tails for continuation
- Flag: "Circuit continues — no board run included for this room"

Only add a board run when:
- The user specifies the distance to the board
- It's clearly a dedicated circuit (cooker, shower, smoke detection)
- The room is the start/end of a circuit

## 7.2 Estimation Method

Cable quantities are estimated from room dimensions using these assumptions:

### Socket Ring Main
- Cable routes along perimeter at socket height (~450mm from FFL to bottom of box)
- Each socket requires a **drop from ceiling void or rise from floor** (depending on cable route)
- Add distance from room to consumer unit (board)
- **Ring**: cable must loop from board → all sockets → back to board

### Lighting Circuit
- Cable routes through ceiling void
- Each downlight/pendant is a daisy-chain point
- Switch drops from ceiling to switch position (~1.2m from floor)
- 2-way switching adds 3-core run between switch positions

## 7.3 Standard Assumptions

| Factor | Default |
|--------|---------|
| Socket height (standard) | **450mm from FFL to bottom of back box** (Building Regs Part M guidance) |
| **Worktop socket height** | **1060mm from FFL to bottom of back box** (worktop 910mm + 150mm above surface) |
| Switch height | **1200mm from FFL to top of back box** (Building Regs Part M guidance) |
| Cable route | Via ceiling void for first fix, or under floor if ground floor |
| Perimeter routing | Cable follows walls, not diagonal |
| Board location | Flag as "distance to board TBC" unless stated |
| Waste factor | **+15%** on all cable quantities |
| Cable clips | 1 clip per 300mm horizontal, 1 per 400mm vertical (T&E) |

**AI behaviour for worktop sockets:** When user mentions "above countertop" / "above worktop" / "worktop sockets" / "kitchen sockets above counter", use **1060mm FFL** height for cable drop calculations, not the standard 450mm.

## 7.4 Quick Estimation Formula

For a room of dimensions L × W × H:

**Socket ring cable** = (2 × (L + W)) × 1.2 + (number of sockets × H) + distance to board × 2
**Lighting cable** = (L × W / 4) × number of lights × 1.3 + switch drops × H
**3-Core (2-way)** = distance between switch positions + (2 × H)

All quantities rounded UP to nearest metre, then +15% waste.

---

# 8. ROOM-SPECIFIC RULES (BS 7671)

## 8.1 Bathrooms

| Zone | Area | Requirements |
|------|------|-------------|
| Zone 0 | Inside bath/shower tray | IPX7, SELV only (max 12V) |
| Zone 1 | Above bath/shower to 2.25m | IPX4 minimum, SELV or 230V with 30mA RCD |
| Zone 2 | 0.6m from Zone 1 boundary | IPX4 minimum, shaver socket (isolating transformer) OK |
| Outside zones | Rest of bathroom | Standard accessories OK, all circuits 30mA RCD protected |

**Bathroom defaults:**
- Downlights in Zone 1: must be IP65 rated (fire-rated and IP65)
- **All switches OUTSIDE the bathroom** on the external wall (not inside). Pull cord only if switch must be inside
- Shaver socket must be BS EN 61558-2-5 isolating transformer type — **always 47mm deep back box**
- Extractor fan: default **Envirovent SIL100T** (timer model), IP45 minimum if in Zone 1. Fan isolator (WMPS3PIF) on external wall
- No socket outlets in Zone 0, 1, or 2 (except shaver)
- Heated towel rail via **flex outlet plate (WMP2FO)** — NOT FCU unless user specifies
- Mirror light: wire to position, client supplies fitting. Check zone compliance
- In-ground lights (e.g. GLO19): check IP rating for zone placement

**Bathroom switching arrangement:**
Switches for bathroom lighting, extractor fan isolator, and any external lights controlled from inside the bathroom should ALL be positioned on the **external wall outside the bathroom entrance**. This is standard practice and BS 7671 compliant. The AI should automatically place bathroom switches outside the room.

## 8.2 Kitchens

**Kitchen defaults:**
- Worktop sockets minimum 150mm above worktop surface
- Dedicated circuit for cooker (45A switch)
- Dedicated circuit for dishwasher, washing machine, tumble dryer (via FCU)
- Consider separate circuit for fridge/freezer (unswitched FCU or dedicated socket)
- Under-cabinet lighting via FCU
- Extract fan: cooker hood usually hardwired or plugged in, not on fan circuit

## 8.3 Bedrooms (Arc Fault Detection)

- **AFDDs recommended** on bedroom circuits (BS 7671 Amendment 2 recommendation)
- Flag for user if rewire/new installation — "Consider AFDD protection for bedroom circuits"

## 8.4 Smoke, Heat & Carbon Monoxide Detection

**New build / rewire defaults (BS 5839-6 Grade D):**
- **Always on a dedicated circuit** — never shared with lighting or other circuits
- Dedicated 6A RCBO (Type B, 30mA)
- **All detectors mains powered, interlinked, with battery backup**
- Cable: 1.5mm² T&E throughout
- Interlinked via hardwire or radio frequency

### Default Products

| Detector Type | Default Product | Alternative | Use |
|---------------|----------------|-------------|-----|
| Smoke alarm (optical) | **Aico Ei146e** | **Aico Ei3016** | Hallway, landing, every habitable room, bedrooms |
| Heat alarm | **Aico Ei144e** | **Aico Ei3014** | Kitchen, garage (where smoke alarms would false alarm) |
| Carbon monoxide alarm | **Aico Ei3018** | — | Any room with fuel-burning appliance (boiler, gas fire, wood burner) |

### Placement Rules
- Minimum: one smoke alarm per floor level
- Heat detector in kitchen (not smoke — cooking causes false alarms)
- Smoke alarm in hallway, landing, and every habitable room
- CO alarm in any room with a fuel-burning appliance or flue passing through
- CO alarm also recommended near boiler / plant room
- All detectors on same interlinked circuit

### AI Behaviour for Detection
- If the transcription mentions "smoke detector" → default to **Ei146e** (or Ei3016)
- If the transcription mentions "heat detector" or "kitchen detector" → default to **Ei144e** (or Ei3014)
- If the transcription mentions "carbon monoxide" / "CO alarm" / "CO detector" → default to **Ei3018**
- All are mains interlinked — NEVER suggest battery-only detectors
- If the job is a full rewire and detection is not mentioned, flag: "Smoke/heat/CO detection not specified — BS 5839-6 requires interlinked detection. Confirm requirements."

---

# 9. SWITCHING ARRANGEMENTS

## 9.1 Critical Rule: Always Install 2-Way Switches

**EVEN FOR 1-WAY CIRCUITS, ALWAYS USE 2-WAY SWITCHES.**

This is standard professional practice. 2-way switches work perfectly in 1-way applications and allow future upgrade to 2-way switching without replacing the switch. When using Hager Sollysta, the default switch for ALL applications (1-way and 2-way) is **WMPS12** (Hager Sollysta 1-gang 2-way switch).

For grid systems, use **WMGS12** (grid 2-way module) for both 1-way and 2-way circuits.

The AI must NEVER spec a 1-way switch. Always use 2-way.

## 9.2 Vocabulary

| Transcription Terms | Switching Type | What It Means | Switch Product |
|--------------------|----------------|---------------|----------------|
| "one way" / "1-way" / "single switch" | **1-Way (install as 2-way)** | One switch controls the light | WMPS12 (still 2-way switch) |
| "two way" / "2-way" / "switch at door and bed" | **2-Way** | Two switches control one light | WMPS12 |
| "intermediate" / "3-way" / "three switches" | **Intermediate** | Three or more switches for one light | WMGS16 (grid intermediate) |
| "dimmer" | **Dimmer switch** | Replaces one of the switch positions | WMDRPXKIT + DM298 |
| "PIR" / "sensor" / "motion" | **PIR switch** | Motion-activated | Wire to position |
| "timer" / "timed" | **Timer switch** | Time-delay, common for bathrooms | — |
| "smart switch" / "WiFi switch" | **Smart switch** | Needs neutral at switch (flag for user) | — |

## 9.3 Switch Plate Count Rules

| Arrangement | Plates Needed | Cable |
|-------------|---------------|-------|
| 1-way, 1 switch | 1× 1-gang **2-way** plate (WMPS12) | 1.5mm² T&E |
| 2-way, 2 switches | 2× 1-gang 2-way plates (WMPS12) | 1.5mm² T&E + 1.5mm² 3-Core & Earth |
| 2-way + dimmer | 1× dimmer plate (WMDRPXKIT + DM298) + 1× 1-gang 2-way (WMPS12) | 1.5mm² T&E + 1.5mm² 3-Core & Earth |
| Intermediate (3 switches) | 2× 1-gang 2-way plates + 1× intermediate plate (WMGS16 grid) | T&E + 3-Core & Earth between all |
| 2 circuits on 1 plate | 1× 2-gang plate | Each gang separately wired |

## 9.3 Gang Consolidation

If multiple circuits switch from the same location, consolidate onto multi-gang plates:
- 2 lighting circuits at same door position → 2-gang switch plate (not 2 separate 1-gang)
- Dimmer + standard switch at same position → 2-gang plate with dimmer module + rocker module
- Flag if more than 4 gangs at one position — consider grid system

---

# 10. SUNDRIES & ACCESSORIES

These items are automatically added based on the installation:

| Item | When to Add | Quantity Rule |
|------|-------------|---------------|
| Earth sleeving (green/yellow) | Every circuit, every accessory | 1m per accessory + 2m per circuit at board |
| Cable clips (T&E) | All cable runs | 1 per 300mm horizontal, 400mm vertical |
| Red / brown sleeving | Switch returns | 100mm per switch connection |
| Wago connectors (221 series) | Maintenance-free connections | 2-3 per light fitting, 1 per FCU connection |
| Connector / junction boxes | Any junction in accessible location | As needed |
| Fire-rated downlight covers | Every fire-rated downlight in insulated ceiling | 1 per downlight |
| Cable glands | External connections | 1 per external fitting |
| Trunking / capping / conduit | Surface installations or as stated | Measured length + 10% |
| Fixings (screws, rawl plugs) | All installations | Bulk allowance per job |
| Labels (circuit chart) | Consumer unit | 1 set per installation |
| Warning labels | All RCDs, dual supply, etc. | As required by BS 7671 |
| Test certificate | All notifiable work | Flag: Part P notification required |

---

# 11. FLOOR PLAN INTEGRATION (OPTIONAL)

## 11.1 Overview

Floor plans are an OPTIONAL supplementary input. The transcription is ALWAYS the primary source of truth. When a floor plan is provided, the AI uses it for validation and context only — never to generate materials independently.

**Not every job will have a floor plan.** Smaller jobs, call-outs, and additions often have no drawings. The system must work perfectly with transcription alone.

## 11.2 What The Floor Plan IS Used For

When a floor plan image is uploaded alongside the transcription, the AI should use it to:

### Dimension Validation
- Cross-check room dimensions stated in the transcription against the floor plan
- If there's a significant discrepancy: [FLAG: "You stated 4×5m but the plan appears to show approximately 4×3.5m — please confirm dimensions"]
- Minor differences (±0.5m) are normal — plans may not be perfectly to scale

### Room Identification
- Help identify which room the sparky is referring to when using vague references like "the room next to the bathroom" or "the one on the left"
- Match room names between transcription and plan labels

### Door & Window Positions
- Validate switch positions — "switch by the door" can be checked against the plan's door location
- Understand room access points for cable routing logic
- Window positions may affect socket placement (below window sill sockets etc.)

### Missing Room Detection
- If the plan shows rooms that the transcription doesn't mention, flag them: [FLAG: "Floor plan shows an en-suite off the master bedroom — not covered in transcription. Confirm if electrical scope is required."]
- This is a PROMPT only — do NOT generate materials for rooms not in the transcription

### Cable Routing Context
- Understand room adjacency for circuit continuation logic
- Identify likely cable routes (which rooms share walls, where the board might be)
- Estimate cable run distances between rooms more accurately

### Property Overview
- Total property size helps estimate main cable runs
- Floor levels (ground/first/second) affect cable routing assumptions
- Location of consumer unit if marked on plan

## 11.3 What The Floor Plan Is NOT Used For

**CRITICAL — The AI must NEVER:**
- Add sockets, lights, switches, or any accessories based on what it sees on the plan
- Override quantities or specifications stated in the transcription
- Assume room requirements from the plan layout
- Generate a materials list for rooms not covered in the transcription
- Count electrical symbols on the plan (these may be architect's suggestions, not the sparky's scope)

The transcription represents what the electrician has actually scoped and priced. The plan is just a visual reference.

## 11.4 Floor Plan Input Formats

The system should accept:
- **PDF** — most common format from architects/builders
- **JPG / PNG** — photos of printed plans, screenshots
- **Multiple pages** — different floors may be on separate pages

The AI should handle:
- Architect's drawings (scaled, detailed)
- Estate agent floor plans (basic layout, approximate dimensions)
- Builder's sketches (rough, hand-drawn)
- Photos of paper plans (may be angled, partially obscured)

## 11.5 AI Behaviour When No Floor Plan Is Provided

When no floor plan is uploaded:
- Parse transcription normally using all knowledge base rules
- Do NOT mention the absence of a floor plan
- Do NOT suggest that a floor plan would help (unless cable routing is particularly ambiguous)
- The system works exactly the same — floor plans are a bonus, not a requirement

## 11.6 AI Behaviour When Floor Plan IS Provided

When a floor plan is uploaded alongside the transcription:
- Acknowledge it briefly: "Floor plan provided — using for reference and validation"
- Process the transcription as the primary source
- Cross-reference against the plan for the validation checks listed in 11.2
- Add any discrepancy flags to the room's flag list
- If the plan shows rooms not in the transcription, add a single global flag listing them

---

# 12. TRANSCRIPTION PARSING RULES

## 12.1 Room Detection

The AI must detect room changes when it hears:
- Explicit room names: "master bedroom", "kitchen", "en-suite", "hallway", "landing"
- Transition phrases: "moving on to", "next room", "now in the", "going into"
- Numbered references: "bedroom 1", "bedroom 2", "bathroom 2"

Each room becomes a separate section in the output with its own:
- Dimensions (if stated)
- Wall type (if stated, or inherited from job-level setting)
- Finish (if stated, or inherited from job-level or previous room)
- Accessories list
- Cable requirements
- Special notes

## 12.2 Job-Level vs Room-Level Settings

Some settings apply to the whole job unless overridden per room:

**Job-level** (stated once, applies everywhere):
- "All studwork throughout" → every room = dry lining boxes
- "All walls are studwork" → ENTIRE JOB, all rooms (even if mentioned in context of one room)
- "Hamilton 74 brushed chrome black inserts throughout" → all rooms
- "Everything on Wago connectors"
- "Ring mains for sockets, radials for kitchen"

**IMPORTANT: "All walls" scope detection.** When the user says "all walls" in any room's context, the AI must determine if this is job-level or room-level:
- "All walls are studwork" / "all walls by count are studwork" → **JOB-LEVEL** — applies to EVERY room
- "All walls in this room are studwork" / "the walls in here are studwork" → **ROOM-LEVEL** — only that room
- If ambiguous, apply as job-level (more common in new builds) and flag for confirmation

**Room-level** (overrides job-level for that room only):
- "But white plastic in the garage"
- "Solid walls in the extension"
- "The walls in this room are dot and dab"
- "Radial in the kitchen"

## 12.3 Mid-Speech Corrections

**Users frequently correct themselves during voice recordings.** The AI must detect self-corrections and use the CORRECTED value, ignoring the original.

### Correction Patterns
| Pattern | Example | AI Should Use |
|---------|---------|---------------|
| "sorry" / "apologies" / "correction" | "one neostat E sorry apologies correct that one neostat version two" | **NeoStat v2** (the corrected value) |
| "actually" / "no wait" / "I mean" | "six sockets actually no eight sockets" | **8 sockets** |
| "scratch that" / "ignore that" | "two pendants scratch that three pendants" | **3 pendants** |
| "or rather" / "well" (corrective) | "solid walls or rather dot and dab" | **Dot and dab** |
| Repeated with different value | "it's a 3-gang no it's a 4-gang" | **4-gang** |

**AI behaviour:** Always use the LAST stated value when a correction is detected. The correction keywords ("sorry", "apologies", "actually", "no", "correction", "scratch that") signal that what follows replaces what came before.

## 12.4 Ambiguity Handling & Flagging Philosophy

**FLAGS ARE A FEATURE, NOT A FAILURE.** The AI should flag anything it's not 100% certain about rather than guess wrong. A quote with 4 flags that takes 2 minutes to confirm is infinitely better than a quote with 0 flags and 3 wrong products.

### The Review Workflow
1. AI parses transcription → generates materials list with flags
2. User reviews in GoZappify → flagged items are highlighted for attention
3. User confirms, corrects, or fills in blanks
4. Corrected data processes into Quote Builder with pricing
5. User corrections feed back into preferences for next time

### When to Flag
The AI must flag when:
- A product choice depends on information not in the transcription
- The user's intent is ambiguous (e.g., "a few" sockets)
- A specific product/fitting needs to be confirmed (client-supplied items)
- Measurements or distances are missing
- The switching arrangement is complex and needs verification
- Any assumption was made that could be wrong

### When NOT to Flag
Do not flag when:
- The knowledge base has a clear default (e.g., ring main for sockets)
- The user's preferences resolve the choice (e.g., Hager Sollysta for white plastic)
- The part number is explicitly stated in the transcription
- Standard BS 7671 requirements are being applied

When the transcription is unclear, the AI must:
1. Make the best assumption based on trade norms
2. **Flag the assumption** in the output for user review
3. Use [FLAG] markers for anything that needs confirmation

Examples:
- Wall type not mentioned → [FLAG: Wall type not specified — assumed studwork. Please confirm.]
- Room dimensions not given → [FLAG: Room dimensions not provided — cable quantities estimated at average room size 4m × 4m. Please confirm.]
- Unusual request → [FLAG: 3 dimmers on one 2-way circuit — please confirm switching arrangement.]
- Client-supplied fittings → [FLAG: Confirm if client supplies wall light fittings]

## 12.5 Quantities

- "A couple" = 2
- "A few" = 3 (flag for confirmation)
- "Some" = flag, ask user for exact number
- "Double socket" / "twin socket" = 1× 2-gang switched socket
- "Single socket" = 1× 1-gang switched socket
- "Pair of sockets" = 2× sockets (flag: confirm if 2× singles or 2× doubles)

## 12.6 Multi-Transcription Job Continuation

**Users may submit multiple transcriptions for the same job.** A sparky might get interrupted during a voice note, or walk the job across multiple visits. The system must handle this gracefully.

### Rules
1. If a job is saved and its status is **not** "ready" or "complete", any new transcription for that job **adds to the existing quote** — it does NOT create a new quote
2. New rooms from subsequent transcriptions are appended to the existing room list
3. If a room already exists and the new transcription mentions it again, the AI should **merge** the data (flag any conflicts for user review)
4. Job-level settings from the first transcription carry forward (finish, wall type, etc.) unless the new transcription explicitly changes them
5. Only when a job is marked as "ready" or "complete" does a new transcription start a fresh quote

### Example Flow
- Transcription 1: Family room, cupboard 1, utility → saves to "West Grove" job
- *User gets interrupted*
- Transcription 2: Boot room, hallway, bedrooms → AI detects this is the same job → appends rooms to existing quote
- Transcription 3: Corrections — "Actually, family room needs 8 sockets not 6" → AI updates existing room data, flags change for confirmation

### AI Behaviour
- When processing a transcription, check if there is an active (non-complete) job that matches
- Carry forward all job-level settings
- Present the output as a per-room list showing which rooms are new vs existing
- Flag any conflicts between transcriptions

## 12.7 Per-Room Output Format

**On larger jobs, the output MUST be organised as a per-room materials list.** Each room is a self-contained section showing:
- Room name
- All accessories with quantities and part numbers
- Cable requirements for that room
- Flags specific to that room

This allows the user to review and confirm room by room, and maps directly to how the sparky walks the site.

## 12.8 Flag Presentation

All flags must be presented to the user in GoZappify's review screen as interactive items. The user manually inputs the answer for each flag. Once all flags are resolved, the quote can be processed into the Quote Builder with pricing.

Flags should be:
- Clearly worded as questions the user can answer
- Grouped by room
- Presented with the AI's best assumption as a default (user can accept or change)
- Colour-coded: amber for "needs confirmation", red for "missing critical info"

---

# 13. PRODUCT MATCHING & PRICING

## 13.1 Product Data Sources (Priority Order)

When resolving part numbers and pricing, the AI and GoZappify use these sources in order:

| Priority | Source | What It Provides |
|----------|--------|-----------------|
| 1 (highest) | **User's Xero/QuickBooks product list** | Real part numbers, descriptions, and last-known pricing from the user's own accounting system |
| 2 | **GoZappify product database (golden records)** | Community-driven product data with canonical descriptions, aliases, and supplier pricing |
| 3 | **Knowledge base defaults** | Fallback part numbers and product names when no match found in sources 1 or 2 |

**AI behaviour:** Always attempt to match against the user's Xero/QuickBooks product list FIRST. This ensures the quote uses products the user actually stocks, buys, and has pricing for. If no match, fall back to GoZappify database, then knowledge base defaults.

## 13.2 Like-for-Like Price Matching

**When multiple suppliers stock similar items, ALWAYS quote using the MORE EXPENSIVE option.** This protects the contractor's profit margin — if they source the cheaper alternative, they pocket the difference.

### Rules
- Match must be **like-for-like**: same type, same size, same function, same specification
- **NEVER** cross-match between finishes (e.g., don't apply chrome accessory pricing to white plastic)
- **NEVER** cross-match between categories (e.g., don't use dry lining box pricing for metal flush boxes)
- When two manufacturers make the same item (e.g., 35mm 2-gang metal flush box), use the **higher price**

### Examples of Valid Like-for-Like Matching
| Item | Supplier A | Supplier B | Quote Using |
|------|-----------|-----------|-------------|
| 35mm 1-gang metal flush box | £0.85 | £1.10 | **£1.10** (higher) |
| 2.5mm² T&E (100m) | £42.00 | £48.50 | **£48.50** (higher) |
| Wago 221 3-way | £0.55 | £0.62 | **£0.62** (higher) |

### Examples of INVALID Matching (never do this)
| Item A | Item B | Why Invalid |
|--------|--------|-------------|
| White plastic socket | Chrome socket | Different finish |
| Dry lining box | Metal flush box | Different type |
| 1.5mm² cable | 2.5mm² cable | Different size |
| SB629 (dry lining) | Metal 2-gang flush | Different wall type |

## 13.3 Supplier Materials List Generation

GoZappify generates TWO output views from the same parsed data:

### View 1: Per-Room Materials List (Review Screen)
- Used for the user to review and confirm each room
- Shows every item grouped by room
- Includes flags, back boxes, cable calculations
- This is what the user sees during the confirmation step

### View 2: Combined Supplier Materials List
- Used to send to suppliers for up-to-date pricing
- **Merges ALL identical items across ALL rooms into single lines with total quantities**
- Sorted by category (accessories, cable, sundries, detection, switching)
- No room breakdown — just a flat list of everything needed for the whole job

### Combining Rules
- Items are combined when they have the **exact same part number**
- Quantities are summed across all rooms
- Cable is summed in metres, rounded up to nearest whole metre (then to nearest available reel size if applicable)
- Sundries are summed (clips, Wagos, sleeving, etc.)

### Example: West Grove Combined Supplier List

From per-room data:
- Family Room: 8× DLT5515000
- Cupboard 1: 2× DLT5515000
- Utility: 8× DLT5515000
- Boot Room: 5× DLT5515000

**Combined line:** DLT5515000 — Collingwood colour/wattage switchable downlight — **Qty: 23**

From per-room data:
- Family Room: 6× WMSS82
- Utility: 4× WMSS82
- Boot Room: 5× WMSS82

**Combined line:** WMSS82 — Hager Sollysta 2G 13A DP Switched Socket — **Qty: 15**

### Supplier List Format
The combined list should be exportable as:
- **PDF** — for emailing to suppliers
- **CSV** — for importing into supplier ordering systems
- **Copy to clipboard** — for pasting into supplier portals

Each line contains: Part Number | Description | Quantity | Unit

---

# 14. OUTPUT FORMAT

The AI must return structured data in JSON format for each room:

```json
{
  "job": {
    "title": "Job description from transcription",
    "scope": "Full rewire / Partial / Addition",
    "default_wall_type": "studwork",
    "default_finish": {
      "range": "Hamilton 74",
      "finish": "brushed_chrome",
      "style": "screwed",
      "insert_colour": "black"
    }
  },
  "rooms": [
    {
      "name": "Master Bedroom",
      "dimensions": { "length": 4.0, "width": 5.0, "height": 2.4 },
      "wall_type": "studwork",
      "finish_override": null,
      "accessories": [
        {
          "type": "2G Switched Socket",
          "quantity": 4,
          "part_number": "WMSS82",
          "part_description": "Hager Sollysta 2G 13A DP Switched Socket",
          "unit_price": null,
          "price_source": "xero | quickbooks | gozappify | none",
          "back_box": "SB629",
          "back_box_description": "35mm Dual Dry Lining Box",
          "circuit": "ring_main",
          "cable_type": "2.5mm T&E"
        }
      ],
      "cable_summary": {
        "2.5mm_te": { "metres": 42, "calculation": "Ring main: perimeter + drops + board" },
        "1.5mm_te": { "metres": 18, "calculation": "Lighting: daisy chain + switch drops" },
        "1.5mm_3ce": { "metres": 8, "calculation": "2-way switching between positions" }
      },
      "flags": [
        "Distance to consumer unit not stated — cable to board estimated at 10m"
      ]
    }
  ],
  "combined_materials": [
    {
      "part_number": "WMSS82",
      "description": "Hager Sollysta 2G 13A DP Switched Socket",
      "total_quantity": 15,
      "unit": "each",
      "unit_price": null,
      "price_source": "xero | quickbooks | gozappify | none"
    },
    {
      "part_number": "DLT5515000",
      "description": "Collingwood colour/wattage switchable downlight",
      "total_quantity": 23,
      "unit": "each",
      "unit_price": null,
      "price_source": "xero | quickbooks | gozappify | none"
    },
    {
      "part_number": "2.5mm_te",
      "description": "2.5mm² Twin & Earth cable",
      "total_quantity": 150,
      "unit": "metres",
      "unit_price": null,
      "price_source": "xero | quickbooks | gozappify | none"
    }
  ],
  "sundries": {
    "earth_sleeving": "30m",
    "cable_clips_2.5mm": "140",
    "cable_clips_1.5mm": "60",
    "wago_221_3way": "12",
    "wago_221_5way": "6",
    "red_sleeving": "2m"
  },
  "consumer_unit": {
    "type": "RCBO board (Hager)",
    "ways": "calculated from circuits + 25% spare",
    "spd": "Type 2 SPD on main board only",
    "flag": "Existing CU condition not stated — confirm if replacement needed"
  },
  "global_flags": [
    "Part P notification required if notifiable work",
    "AFDD recommended for bedroom circuits (BS 7671 Amd 2)"
  ]
}
```

---

# 15. LEARNING & CORRECTIONS

## 15.1 User Correction Feedback

When a user reviews and corrects the AI output, the system should capture:
- What the AI assumed vs what the user changed
- The correction category (wrong product, wrong quantity, wrong back box, wrong cable size, missing item)
- Whether this should update the user's preferences or the global rules

## 15.2 User Preference Updates

Corrections that should update user preferences:
- "I always use X brand for Y finish" → update brand map
- "I use metal boxes on studwork" → update wall type mapping
- "I wire kitchens as radials" → update circuit defaults
- "I use push-fit connectors not Wagos" → update sundries

## 15.3 Community Learning

Corrections that many users make consistently should update global defaults:
- If 70%+ of users change a default, flag it for global review
- Product range popularity data informs default suggestions for new users
- Regional variations may apply (different suppliers popular in different areas)

---

# 16. COMMON TRANSCRIPTION PATTERNS

These are examples of how sparkies actually talk on site. The AI must handle all of these naturally:

**Setting the job scope:**
- "Right so this is a full rewire, 3-bed semi"
- "Just an addition, extending the kitchen"
- "Partial rewire, just the upstairs"

**Setting finishes:**
- "Hamilton 74 brushed chrome black inserts throughout"
- "White plastic everywhere except the lounge and master, they want chrome"
- "Same as last job, Hager Sollysta white"
- "Customer wants screwless matt black in the living room"

**Describing a room:**
- "Master bedroom, about 4 by 5, 2.4 ceilings, studwork"
- "Kitchen, big one, maybe 6 by 4, solid walls on two sides, stud partition to the dining room"
- "Hallway, narrow, 1.2 wide, about 8 metres long, standard height"

**Specifying accessories:**
- "4 doubles, 2 either side of the bed"
- "6 spots, 2-way dimmer, switch at the door and by the bed"
- "Double sockets on the kitchen worktop, I'd say 6 of them, plus 2 behind the appliances"
- "Cooker point, high level over the hob"
- "Outside light, PIR, above the back door"
- "USB sockets either side of the bed"
- "Shaver socket in the en-suite"
- "TV point and data point behind where the telly goes"

**Wall type context:**
- "All studwork in here"
- "This room's been dot and dabbed"
- "Solid walls, we'll be chasing"
- "The carpenter's noggined out for us so metal boxes"
- "Surface mount in the garage, just clip and pin"

**Switching:**
- "2-way at the door and the bed"
- "3-way in the hallway, switch at each end and one at the top of the stairs"
- "Dimmer on the main lights, standard switch on the spots"
- "PIR in the hallway, linked to the porch light"

---

# DOCUMENT VERSION

- **Version**: 1.0
- **Last Updated**: February 2026
- **Standards Reference**: BS 7671:2018 + Amendment 2
- **Default Supplier Preferences**: Hager Sollysta (white), Hamilton 74 (brushed chrome)
- **Notes**: This is a living document. User corrections and community feedback continuously improve accuracy.
