"""Minecraft redstone mechanisms as Titanfall 2 script movers.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.

Titanfall 2 has no redstone, so each circuit becomes a scripted approximation:

- **Circuits** are redstone parts (wire, repeaters, torches, inputs, outputs)
  within two blocks of each other, which covers power passing through one block.
- **Inputs:** buttons and levers are used with the use key while looking at them
  (buttons spring back after a second); pressure plates are on while a pilot
  stands on them.
- **Outputs**, which all switch together when the circuit's state flips:
  pistons move the block in front of them (sticky pistons that are already
  extended pull their head and block back), doors swing 90 degrees about their
  hinge edge, and TNT explodes after a short fuse.
- Not reproduced: timing and logic (repeater delays, torch inversion, clocks),
  so circuits that sequence or combine inputs simply toggle everything at once;
  dispensers, lamps, note blocks and redstone wire visuals stay static.

``mechanisms`` finds them; the converter emits each moving group as a
``func_brush`` without an origin key (remap stores brush models in world
coordinates, and the engine adds the origin again) and ``level_script``
writes the Squirrel that drives them.
"""
from collections import defaultdict

PARTS = {'redstone_wire', 'repeater', 'comparator', 'redstone_torch', 'redstone_wall_torch', 'piston', 'sticky_piston',
         'piston_head', 'stone_button', 'oak_button', 'spruce_button', 'birch_button', 'polished_blackstone_button', 'lever',
         'stone_pressure_plate', 'oak_pressure_plate', 'light_weighted_pressure_plate', 'heavy_weighted_pressure_plate',
         'iron_door', 'oak_door', 'spruce_door', 'birch_door', 'dark_oak_door', 'tnt', 'dispenser', 'redstone_lamp',
         'note_block', 'redstone_block', 'observer', 'dropper', 'tripwire_hook', 'target', 'daylight_detector'}
DIRECTIONS = {'up': (0, 1, 0), 'down': (0, -1, 0), 'north': (0, 0, -1), 'south': (0, 0, 1), 'east': (1, 0, 0), 'west': (-1, 0, 0)}
# Blocks a piston cannot move, and air.
IMMOVABLE = {'air', 'cave_air', 'obsidian', 'bedrock', 'piston_head', 'water', 'lava', 'chest', 'barrier'}


def name_of(state):
    return state['Name'].split(':')[-1]


def is_button(n): return n.endswith('_button')
def is_plate(n): return n.endswith('_pressure_plate')
def is_door(n): return n.endswith('_door')


def add(p, d, k=1): return (p[0]+d[0]*k, p[1]+d[1]*k, p[2]+d[2]*k)


def circuits(parts):
    """Group part positions within two blocks of each other."""
    seen = set(); groups = []
    for start in sorted(parts):
        if start in seen: continue
        stack = [start]; seen.add(start); group = []
        while stack:
            q = stack.pop(); group.append(q)
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    for dz in range(-2, 3):
                        r = (q[0]+dx, q[1]+dy, q[2]+dz)
                        if r in parts and r not in seen: seen.add(r); stack.append(r)
        groups.append(sorted(group))
    return groups


def mechanisms(blocks):
    """Working circuits: [{'inputs': [(kind, pos, props)], 'moves': [{'cells', 'delta'}],
    'doors': [{'cells', 'hinge', 'turn'}], 'tnt': [pos]}], plus every moving cell."""
    world = {(x, y, z): s for x, y, z, s in blocks}
    parts = {p: s for p, s in world.items() if name_of(s) in PARTS}
    result = []; moving = set()
    for group in circuits(parts):
        inputs = []; moves = defaultdict(list); doors = []; tnt = []
        for p in group:
            n = name_of(parts[p]); props = parts[p].get('Properties', {})
            if is_button(n) or n == 'lever': inputs.append(('button' if is_button(n) else 'lever', p, props))
            elif is_plate(n): inputs.append(('plate', p, props))
            elif n == 'tnt': tnt.append(p)
            elif n in ('piston', 'sticky_piston'):
                d = DIRECTIONS[props.get('facing', 'up')]
                head = add(p, d); front = add(p, d, 2)
                if props.get('extended') == 'true':
                    cells = [head] if head in world and name_of(world[head]) == 'piston_head' else []
                    if n == 'sticky_piston' and front in world and name_of(world[front]) not in IMMOVABLE | PARTS:
                        cells.append(front)
                    if cells: moves[tuple(-v for v in d)] += cells
                elif head in world and name_of(world[head]) not in IMMOVABLE | PARTS:
                    moves[d].append(head)
            elif is_door(n) and props.get('half') == 'lower':
                upper = add(p, (0, 1, 0))
                facing = DIRECTIONS[props.get('facing', 'north')]
                # Closed, the door is a thin slab on the side away from its facing; it
                # turns about the end its hinge property names.
                right = (-facing[2], 0, facing[0])
                side = -1 if props.get('hinge', 'left') == 'left' else 1
                hinge = (p[0]+0.5+(-facing[0]*0.5)+right[0]*side*0.5, p[1], p[2]+0.5+(-facing[2]*0.5)+right[2]*side*0.5)
                doors.append({'cells': [p, upper] if upper in world else [p], 'hinge': hinge,
                              'turn': 90 if side < 0 else -90})
        if not inputs or not (moves or doors or tnt): continue
        movegroups = [{'cells': sorted(set(c)), 'delta': d} for d, c in sorted(moves.items())]
        for m in movegroups: moving.update(m['cells'])
        for d in doors: moving.update(d['cells'])
        moving.update(tnt)
        result.append({'inputs': inputs, 'moves': movegroups, 'doors': doors, 'tnt': sorted(tnt)})
    # A cell claimed by two circuits moves with the first.
    claimed = set()
    for c in result:
        for m in c['moves']: m['cells'] = [p for p in m['cells'] if p not in claimed]; claimed.update(m['cells'])
        c['moves'] = [m for m in c['moves'] if m['cells']]
    return result, moving


def vec(p):
    return '< '+', '.join(f'{v:.1f}' for v in p)+' >'


# Must precede every function in the level script.
HEADER = 'global function RS_SetCircuit\n'


def level_script(mechs, transform, scale):
    """Squirrel functions RS_Init (thread it from map init) and helpers. Movers are
    named mrvn_rs_<circuit>_<n>; transform maps block coordinates to world units."""
    lines = []
    names, homes, deltas, pivots, turns, circuit_of, kinds = [], [], [], [], [], [], []
    for i, c in enumerate(mechs):
        for j, m in enumerate(c['moves']):
            d = transform(m['delta']); o = transform((0, 0, 0))
            names.append(f'mrvn_rs_{i}_m{j}'); kinds.append(0); circuit_of.append(i)
            deltas.append(tuple(a-b for a, b in zip(d, o))); pivots.append((0, 0, 0)); turns.append(0)
        for j, door in enumerate(c['doors']):
            names.append(f'mrvn_rs_{i}_d{j}'); kinds.append(1); circuit_of.append(i)
            deltas.append((0, 0, 0)); pivots.append(transform(door['hinge'])); turns.append(door['turn'])
        for j, t in enumerate(c['tnt']):
            names.append(f'mrvn_rs_{i}_t{j}'); kinds.append(2); circuit_of.append(i)
            deltas.append((0, 0, 0)); pivots.append(transform((t[0]+.5, t[1]+.5, t[2]+.5))); turns.append(0)
    inputs = [(k, transform((p[0]+.5, p[1]+(.05 if k == 'plate' else .5), p[2]+.5)), i)
              for i, c in enumerate(mechs) for k, p, _ in c['inputs']]
    kind_id = {'button': 0, 'lever': 1, 'plate': 2}
    text = f'''
// Redstone mechanisms (minecraft_redstone.py): {len(mechs)} circuits, {len(names)} movers, {len(inputs)} inputs.
// RS_SetCircuit is global (HEADER) so the console can call it: script RS_SetCircuit( 0, true )
struct
{{
 array<string> names
 array<int> kinds
 array<int> circuitOf
 array<vector> deltas
 array<vector> pivots
 array<float> turns
 array<int> inputKinds
 array<vector> inputPos
 array<int> inputCircuit
 array<entity> brushes
 array<entity> movers
 array<vector> homes
 array<bool> circuitOn
 array<bool> plateDown
 array<bool> exploded
}} file

void function RS_Init()
{{
 file.names = [ {', '.join('"'+n+'"' for n in names)} ]
 file.kinds = [ {', '.join(map(str, kinds))} ]
 file.circuitOf = [ {', '.join(map(str, circuit_of))} ]
 file.deltas = [ {', '.join(vec(d) for d in deltas)} ]
 file.pivots = [ {', '.join(vec(p) for p in pivots)} ]
 file.turns = [ {', '.join(f'{t:.1f}' for t in turns)} ]
 file.inputKinds = [ {', '.join(str(kind_id[k]) for k, _, _ in inputs)} ]
 file.inputPos = [ {', '.join(vec(p) for _, p, _ in inputs)} ]
 file.inputCircuit = [ {', '.join(str(i) for _, _, i in inputs)} ]
 WaitFrame()
 for ( int c = 0; c < {len(mechs)}; c++ )
  file.circuitOn.append( false )
 foreach ( int i, string name in file.names )
 {{
  entity brush = GetEntByScriptName( name )
  entity mover = null
  if ( IsValid( brush ) )
  {{
   // Doors turn about their hinge; everything else moves from the world origin.
   vector at = < 0, 0, 0 >
   if ( file.kinds[i] == 1 )
    at = file.pivots[i]
   mover = CreateScriptMover( at, < 0, 0, 0 > )
   brush.SetParent( mover, "", true, 0 )
  }}
  else
   printt( "[MRVN.Redstone] missing mover", name )
  file.brushes.append( brush )
  file.movers.append( mover )
  vector home = < 0, 0, 0 >
  if ( IsValid( mover ) )
   home = mover.GetOrigin()
  file.homes.append( home )
  file.exploded.append( false )
 }}
 foreach ( vector p in file.inputPos )
  file.plateDown.append( false )
 AddCallback_OnClientConnected( RS_OnClientConnected )
 foreach ( entity player in GetPlayerArray() )
  RS_OnClientConnected( player )
 printt( "[MRVN.Redstone] ready", file.movers.len(), "movers" )
 while ( true )
 {{
  foreach ( int i, vector p in file.inputPos )
  {{
   if ( file.inputKinds[i] != 2 )
    continue
   bool down = false
   foreach ( entity player in GetPlayerArray() )
   {{
    vector o = player.GetOrigin()
    if ( IsAlive( player ) && fabs( o.x - p.x ) < {scale*0.75:.1f} && fabs( o.y - p.y ) < {scale*0.75:.1f} && o.z - p.z > -8.0 && o.z - p.z < 24.0 )
     down = true
   }}
   if ( down != file.plateDown[i] )
   {{
    file.plateDown[i] = down
    RS_SetCircuit( file.inputCircuit[i], down )
   }}
  }}
  wait 0.1
 }}
}}

void function RS_OnClientConnected( entity player )
{{
 AddButtonPressedPlayerInputCallback( player, IN_USE, RS_OnUse )
}}

void function RS_OnUse( entity player )
{{
 vector eye = player.EyePosition()
 vector view = player.GetViewVector()
 int best = -1
 float bestDistance = {scale*2.5:.1f}
 foreach ( int i, vector p in file.inputPos )
 {{
  if ( file.inputKinds[i] == 2 )
   continue
  vector to = p - eye
  float distance = Length( to )
  if ( distance < bestDistance && DotProduct( Normalize( to ), view ) > 0.8 )
  {{
   best = i
   bestDistance = distance
  }}
 }}
 if ( best < 0 )
  return
 int c = file.inputCircuit[best]
 if ( file.inputKinds[best] == 1 )
  RS_SetCircuit( c, !file.circuitOn[c] )
 else
  thread RS_PressButton( c )
}}

void function RS_PressButton( int c )
{{
 RS_SetCircuit( c, true )
 wait 1.5
 RS_SetCircuit( c, false )
}}

void function RS_SetCircuit( int c, bool on )
{{
 if ( file.circuitOn[c] == on )
  return
 file.circuitOn[c] = on
 int moved = 0
 foreach ( int i, entity mover in file.movers )
 {{
  if ( file.circuitOf[i] != c || !IsValid( mover ) )
   continue
  moved++
  if ( file.kinds[i] == 0 )
  {{
   vector target = file.homes[i]
   if ( on )
    target = target + file.deltas[i]
   mover.NonPhysicsMoveTo( target, 0.15, 0.0, 0.0 )
  }}
  else if ( file.kinds[i] == 1 )
  {{
   float yaw = 0.0
   if ( on )
    yaw = file.turns[i]
   mover.NonPhysicsRotateTo( < 0, yaw, 0 >, 0.3, 0.0, 0.0 )
  }}
  else if ( on && !file.exploded[i] )
  {{
   file.exploded[i] = true
   thread RS_Explode( i )
  }}
 }}
 printt( "[MRVN.Redstone] circuit", c, on, moved, "movers" )
}}

void function RS_Explode( int i )
{{
 wait 2.0
 vector origin = file.pivots[i]
 if ( IsValid( file.brushes[i] ) )
  file.brushes[i].Destroy()
 RadiusDamage( origin, svGlobal.worldspawn, svGlobal.worldspawn, 150, 1500, {scale*1.5:.1f}, {scale*4:.1f}, 0, 0, 5000, 0, eDamageSourceId.mp_weapon_frag_grenade )
}}
'''
    return text
