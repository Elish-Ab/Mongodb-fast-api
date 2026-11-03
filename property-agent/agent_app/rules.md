# Pivotal rules (plain English — this becomes the "Rules" tab in the Sheet)

## Lot
- Lot size (B6): use the county assessor's lot square feet.
- Lot width (B7): use `frontage.width_ft` from the parcel map. It is the narrow end of the lot; on a corner lot, the narrower end (which side is the front doesn't matter). Round to the nearest foot (Pivotal's samples use whole feet: 52, 74, 96). In the note, give the measured width and the nearest standard lot size (30/40/45/50/55/60 ft) when within 3 ft of one.
- If `frontage.needs_check` is true, or rectangularity is below 0.85, still give the width but mark it "check" and explain why.
- Lot depth is a formula in the sheet (lot size ÷ width). Do not fill it.
- Corner lot (B12): "Yes" if `frontage.corner_lot` is true, otherwise "No".
- Alley/Easement/Road (B11) means usable access from an alley or road. Any 2–30 ft strip beside the lot is checked:
  - Seattle (`narrow_strips` from seattle_map_layers): "Yes" if the strip is alley or street right-of-way AND its 2015 surface is "solid (paved)". If it is right-of-way but gravel, vegetated or unmapped, answer "No", status "check", and say so in the note (e.g. "16 ft unpaved alley right-of-way on the east side"). If it is not right-of-way (easement, tract, no record), answer "No", status "check", and describe it.
  - Outside Seattle: no surface data yet. If there is a strip, answer "Yes", status "check", and give its width.
  - No strip at all: "No".

## City map layers (count a layer if it touches any part of the lot)
- ECAs (B13): list each environmentally critical area that touches the lot, with its share of the lot. If none, write "N/A".
- Average slope (B14): no elevation data yet. If no steep slope or slide area touches the lot, write 0 and mark "check" (flat is likely, not measured). If one does, leave it empty, status "missing", and name the area in the note.
- Frequent transit (B16), Seattle: "Yes" if any part of the lot is inside a quarter-mile (1,320 ft) walkshed of a frequent transit stop (`frequent_transit` layer, SDCI walksheds updated Dec 2025), otherwise "No".
- Frequent transit (B16), Bellevue: "Yes" if the nearest frequent-transit stop is within a quarter mile (1,320 ft) of the lot, otherwise "No". Put the distance in the note. This is a straight-line distance, and the walking route is longer (cul-de-sacs, no through paths). If the stop is 900–1,320 ft away, still answer "Yes" but mark "check" and say the walk may be over a quarter mile.
- Zoning (B23): the cell is "Zoning (Seattle)" and only accepts NR, RSL, LR1, LR2, LR3 (the sheet's formulas use Seattle rules).
  - Seattle: use the city's zoning map (current code); the assessor's zoning can be out of date. If the zone is not one of the five, put the real zone in the note and mark "check".
  - Outside Seattle: give the Seattle equivalent. Single-family and low-density residential zones (Bellevue SR-1 to SR-4 and R-1 to R-7.5, Kirkland RSA/RSX, Redmond R-4 to R-6, county R-1 to R-8, etc.) become "NR". Put the local zone in the note (e.g. "Bellevue SR-3, Seattle equivalent NR"). Multifamily or commercial zones: give the closest of the five and mark "check".
- Bellevue streams: a stream within 100 ft of the lot counts as an ECA ("Stream", with its distance).
- MHA designation (B25) and MHA area (B26): MHA is a Seattle program. Outside Seattle, or if the lot is not in an MHA zone, write "N/A" in both.

## Other
- Address (B3): the assessor's site address.
- Jurisdiction (B21) must be one of: Seattle, Bellevue, Kirkland, Redmond, Other.
- Year renovated (B50): use the renovation/effective year if it is newer than the year built; otherwise use the year built.
- Never guess. If no tool returned the value, mark it "missing".
- Recent System Update (B51): the year of the most recent MAJOR system update, from `permit_history` (county permits, plus Seattle building/electrical/trade permits in Seattle). Major means a permit that renews a whole system of the house: a rewire, a re-pipe/re-plumb, or a structural/framing remodel or addition of the living space. These do NOT count: an electrical service change or panel upgrade alone, furnace/heat pump/HVAC, refrigeration, water heater, sewer or side sewer, roof, solar, fences, decks, garages/carports and other accessory buildings, demolition, and permits that were never issued or were cancelled. If none qualifies, write 0. If a permit is borderline (the description is too short to tell), still write 0 or the year as the rule says, mark "check", and name the permit in the note. In the note, list the newest permits you looked at (number, year, one-word reason it does or doesn't count). Outside Seattle only the county permits are available; say so in the note.
