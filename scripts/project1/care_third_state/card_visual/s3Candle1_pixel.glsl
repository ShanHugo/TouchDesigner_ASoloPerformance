// S3 Candle Light x Illumination (teacher's visual plan, section 4)
// No person. One flame ("the inner flame") that grows, warms and lights the space.
// The platform ellipse is exactly the card table's ellipse, so when the table fades
// out after the card locks, the platform is already there, lit by the flame.
// Work space q: x in screen-height units (aspect-correct), y = uv.y (0 bottom, 1 top).
uniform float uSize;    // effect_controller flameSize
uniform float uGain;    // flameGain
uniform float uStab;    // flameStability (0 = unsteady, 1 = calm)
uniform float uIgnite;  // flameIgnite: flash when the card lands in the flame
uniform float uTime;
// --- Act 3 card branch: the four cards change ONLY the candle's colour.
// Driven by card_sense/cardBranch1 (crossfaded there), palettes in cardPalette1.
uniform vec3 uColEdge;   // flame outer
uniform vec3 uColMid;    // flame inner
uniform vec3 uColCore;   // flame core
uniform vec3 uColLight;  // colour of the light the flame casts on the space
out vec4 fragColor;
const float A = 16.0 / 9.0;

float hash(float n) { return fract(sin(n) * 43758.5453); }
float noise1(float x) { float i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f); return mix(hash(i), hash(i + 1.0), f); }

// distance to an ellipse outline (first-order), in q units
float ellipseLine(vec2 q, vec2 c, vec2 r, float w)
{
    vec2 d = q - c;
    float f = (d.x * d.x) / (r.x * r.x) + (d.y * d.y) / (r.y * r.y) - 1.0;
    vec2 g = 2.0 * vec2(d.x / (r.x * r.x), d.y / (r.y * r.y));
    float dist = abs(f) / max(length(g), 1e-4);
    return 1.0 - smoothstep(w * 0.5, w * 1.5, dist);
}

void main()
{
    vec2 uv = vUV.st;
    vec2 q = vec2((uv.x - 0.5) * A, uv.y);
    float px = 1.0 / 720.0;
    vec2 base = vec2(0.0, 0.335);

    // breathing: unsteady early, calm once stable
    float unst = 1.0 - clamp(uStab, 0.0, 1.0);
    float breathe = 1.0 + unst * 0.22 * (noise1(uTime * 3.1) - 0.5) + 0.04 * sin(uTime * 1.3);
    float gain = clamp(uGain, 0.0, 1.0) * breathe;

    // ---- flame (teardrop), height grows with flameSize
    float H = (0.04 + 0.24 * clamp(uSize, 0.0, 1.0)) * (1.0 + unst * 0.08 * (noise1(uTime * 5.3 + 7.0) - 0.5));
    vec2 d = q - base;
    float y = d.y / H;
    float sway = unst * 0.16 * H * (noise1(uTime * 2.7 + y * 2.0) - 0.5) * 2.0 * clamp(y, 0.0, 1.0);
    // teardrop: round bottom (circle below y=0.25), tapering tip above
    float R0 = 0.34 * H * pow(0.75, 0.85);
    float bottom = R0 * sqrt(max(0.0, 1.0 - pow((0.25 - y) / 0.55, 2.0)));
    float top = 0.34 * H * pow(clamp(1.0 - y, 0.0, 1.0), 0.85);
    float prof = y < 0.25 ? bottom : top;
    float e = abs(d.x - sway) / max(prof, 1e-4);
    float inside = step(-0.3, y) * step(y, 1.0) * step(1e-4, prof);
    float body = (1.0 - smoothstep(0.45, 1.0, e)) * inside;
    float core = (1.0 - smoothstep(0.0, 0.55, e)) * smoothstep(-0.2, 0.08, y) * (1.0 - smoothstep(0.3, 0.75, y)) * inside;
    vec3 flameCol = body * mix(uColEdge, uColMid, clamp(1.0 - e, 0.0, 1.0)) + core * uColCore;
    // unlit until the card lands (flameGain rests at 0): no flame at all, not a dim one
    float lit_on = smoothstep(0.02, 0.12, clamp(uGain, 0.0, 1.0));
    flameCol *= (0.35 + 0.95 * gain) * lit_on;

    // ---- light falloff from the flame: what the flame can "reveal" of the space
    vec2 fc = base + vec2(0.0, 0.45 * H);
    float reach = 0.25 + 0.75 * gain;
    float lit = 0.035 + 0.95 * gain * exp(-length(q - fc) / reach);

    // ---- space: platform (= table ellipse), its lower rim, floor ring, back arc, halo ring
    vec2 pd0 = (q - vec2(0.0, 0.32)) / vec2(0.601, 0.245);
    vec2 pd1 = (q - vec2(0.0, 0.25)) / vec2(0.601, 0.245);
    float outsidePlat = smoothstep(0.98, 1.02, min(length(pd0), length(pd1)));
    float lines = 0.0;
    lines += 1.0 * ellipseLine(q, vec2(0.0, 0.32), vec2(0.601, 0.245), 1.6 * px);
    lines += 0.6 * ellipseLine(q, vec2(0.0, 0.25), vec2(0.601, 0.245), 1.4 * px) * step(q.y, 0.25);
    lines += 0.45 * ellipseLine(q, vec2(0.0, 0.16), vec2(1.15, 0.2), 1.3 * px) * outsidePlat;
    lines += 0.35 * ellipseLine(q, vec2(0.0, 0.12), vec2(1.55, 0.86), 1.3 * px) * step(0.12, q.y) * outsidePlat;
    float haloR = 0.06 + 0.22 * gain;
    lines += 0.5 * gain * ellipseLine(q, fc, vec2(haloR, haloR), 1.3 * px);
    vec3 lineCol = uColLight * lines * lit;

    // warm ambient on the platform top as it gets lit
    vec2 pd = (q - vec2(0.0, 0.32)) / vec2(0.601, 0.245);
    float plat = (1.0 - smoothstep(0.85, 1.0, length(pd))) * 0.12 * gain * exp(-length(q - fc) / reach);

    // ---- ignition flash when the card lands
    float flash = uIgnite * 0.8 * exp(-length(q - fc) / (0.03 + 0.05 * uIgnite));

    // the ambient wash was (1.0, 0.70, 0.40) against a line colour of (1.0, 0.74, 0.44):
    // keep that exact ratio so card 0 renders pixel-identically to before the branch
    vec3 ambCol = uColLight * vec3(1.0, 0.9459, 0.9091);
    vec3 col = flameCol + lineCol + ambCol * (plat + flash);
    fragColor = TDOutputSwizzle(vec4(col, 1.0));
}
