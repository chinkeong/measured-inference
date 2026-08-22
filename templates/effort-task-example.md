# Animated Aquarium -- LLM Prompt

Create a single self-contained HTML file that renders an animated
deep-ocean aquarium. Requirements:

## File constraints

1. One file only. All CSS and JavaScript inline. No external
   resources of any kind: no CDN links, no images, no fonts, no
   network requests. The page must work offline when opened from a
   local file.
2. Draw the scene on a canvas element that always fills the browser
   window and re-adapts when the window is resized, with no
   stretching artifacts and no scrollbars.

## CONFIG object

All tunable parameters must be named constants in one CONFIG object
at the top of the script so a reader can adjust them. Include at
minimum:

- Fish count per species
- Speed multiplier (global, affects all creatures)
- Bubble spawn interval in milliseconds
- Jellyfish count
- Crab count
- Maximum simultaneous bubbles
- Day/night cycle duration in seconds (0 to disable)

## Sea creatures (required)

Implement at least the following. Each must be visually distinct
(different shape, color, and drawing logic) and have its own
movement behavior. Be creative with the exact appearance -- the
descriptions below are guidelines, not pixel specs.

### Fish -- at least 3 species, at least 2 of each

1. **Tropical fish** -- oval body, warm palette (oranges, yellows,
   whites), horizontal stripes or bands. Movement: steady horizontal
   glide, reverses direction at canvas edges, slight vertical drift.

2. **Angelfish** -- tall diamond or kite-shaped body, elongated
   dorsal and ventral fins, cool palette (blues, purples, silvers).
   Movement: slower horizontal travel with a pronounced sinusoidal
   vertical bob. The difference from species 1 must be obvious
   within seconds.

3. **Small schooling fish** -- tiny, simple silhouettes that move as
   a loose school. They should loosely follow a shared heading that
   slowly rotates, with each individual adding small random offsets
   so the group shimmers rather than moving rigidly. At least 8 in
   the school.

### Jellyfish -- at least 2

Translucent, bell-shaped bodies with trailing tentacles. The bell
should visibly pulse (expand/contract) to propel the jellyfish
upward; between pulses it drifts slowly downward and sideways.
Tentacles should sway and trail behind the movement. Use
semi-transparent fills so the jellyfish look ghostly and
luminescent. They move independently of fish.

### Bottom dwellers

4. **Crab** -- at least 1. Sits on the sandy floor. Occasionally
   scuttles sideways in short bursts, pauses, then scuttles again.
   Draw with a round body, eyestalks, and visible claws/pincers.

5. **Lobster** -- at least 1. Larger than the crab, reddish-brown,
   with a segmented tail, large front claws, and antennae. Moves
   slowly along the bottom, occasionally stops and raises its claws.

6. **Starfish** -- at least 1. Five-armed, textured, resting on the
   floor or on a rock. Moves extremely slowly (almost imperceptibly)
   or stays still. Subtle color -- ochre, rust, or muted purple.

### Seahorse -- at least 1

Upright posture, curled tail, snout. Bobs vertically in place or
drifts very slowly. Tail may curl and uncurl gently.

### Sea turtle -- at least 1

Distinct shell pattern (hexagonal or scute pattern drawn on the
shell). Flippers animate in a slow rowing stroke. Moves gracefully
across the scene at a leisurely pace, occasionally changing
direction in gentle arcs, not sharp turns.

## Shells and static sea floor objects

- **Seashells** -- at least 3 different shells scattered on the
  floor: a spiral conch, a scallop/fan shape, and a small cowrie or
  similar. Give each a slightly different size and tint.
- **Coral formations** -- at least 2 clusters of branching or
  brain coral near the bottom, with warm pinks, oranges, or reds.
- **Sea anemone** -- at least 1, with a cluster of waving tentacles
  rooted to a rock or the floor. Tentacles sway gently with
  a current-like motion.
- **Seaweed / kelp** -- at least 3 stalks of different heights that
  sway gently, rooted at the bottom. Vary the green hue per stalk.
- **Rocks** -- a few rounded stones of varying sizes on the floor.

## Bubbles

Bubbles appear near the bottom, rise to the top with gentle
side-to-side wobble, and keep respawning indefinitely. They should
look translucent with a subtle specular highlight. Slight size
variation.

## Environment and atmosphere

- **Water background** -- a vertical gradient from dark deep blue at
  the top to a lighter teal-blue near the bottom, suggesting depth.
- **Caustic light rays** -- subtle, slow-moving shafts of pale light
  from the surface, barely visible. They add atmosphere without
  overwhelming the scene.
- **Sandy floor** -- a textured strip at the bottom with slight
  undulation, small pebbles, and a warm sandy color.
- **Particle motes** -- optional: tiny floating specks drifting
  slowly in the water to suggest organic matter. Very subtle.
- **Day/night cycle** (optional but encouraged) -- if enabled in
  CONFIG, the overall scene brightness slowly oscillates between
  a brighter daytime palette and a darker nighttime palette. During
  "night" jellyfish and certain fish could glow faintly.

## Movement rules

- All creatures must remain visible: turn, wrap, or bounce at canvas
  edges.
- Each species must have a clearly distinct movement pattern. A
  viewer should be able to tell species apart by movement alone
  within 15 seconds.
- Creatures should not cluster in one area. Distribute them across
  the tank.
- Bottom dwellers stay on the floor. Jellyfish occupy the upper
  half. Fish and turtle roam the middle. Seahorse stays near decor.

## Creative freedom

The descriptions above set a minimum. You are encouraged to add:

- Additional species or variants (pufferfish, manta ray, eel,
  clownfish in an anemone, etc.)
- Decorative details (sunken treasure chest, ship wheel, anchor,
  ceramic diver figurine, etc.)
- Interaction touches (fish avoiding each other, schooling fish
  reacting to edges, crab retreating when a fish swims near)
- Ambient effects (ripple overlay on the surface, shadow on the
  floor, depth-of-field blur for distant fish)
- Sound-reactive elements if the Web Audio API is available

Surprise me. The goal is a beautiful, living aquarium that someone
would leave open as a desktop decoration.

## Quality

- The page must produce no console errors.
- Animation should be smooth at 60 fps on a mid-range machine. Use
  requestAnimationFrame, delta-time, and avoid unnecessary
  allocations in the render loop.
- All drawing must use the Canvas 2D API (no WebGL required, but
  allowed as a bonus layer).

Output only the complete HTML file content, starting with
`<!DOCTYPE html>`. No explanations, no markdown fences, no extra
text.
