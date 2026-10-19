// S1 church space, rebuilt as LIGHT rather than line work: the reference frames read
// as a church because of broad beams, fog and tonal masses, not because of wireframe.
// Kept: a cross, an altar with two candles, a few soft floor steps. Removed: columns,
// lintels and the floor grid (the artist found it unclear and too busy).
uniform float uReveal;
uniform float uOpacity;   // overall strength
uniform float uBeams;     // beam strength
uniform float uTime;
uniform vec4  uFog;       // density (0 = the old flat haze), uv scale, drift speed, floor bias
out vec4 fragColor;
const float A = 16.0 / 9.0;

float segDist(vec2 p, vec2 a, vec2 b)
{
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0);
    return length(pa - ba * h);
}

// mirrored wrap so a drifting sample never crosses a seam
vec2 mirrorUV(vec2 uv)
{
    vec2 f = fract(uv * 0.5) * 2.0;
    return vec2(f.x > 1.0 ? 2.0 - f.x : f.x, f.y > 1.0 ? 2.0 - f.y : f.y);
}

// two layers of the Noise TOP at different scales and drifts = air with depth.
// (a procedural sin-hash noise written here rendered as rectangular blocks on this
// machine - the Noise TOP is the reliable source.)
float fogField(vec2 uv, float scale, float speed)
{
    float t = uTime * speed;
    float n1 = texture(sTD2DInputs[0], mirrorUV(uv * scale + vec2(t, t * 0.35))).r;
    float n2 = texture(sTD2DInputs[0], mirrorUV(uv * scale * 2.3 + vec2(-t * 0.6, t * 0.22))).r;
    return clamp(0.62 * n1 + 0.38 * n2, 0.0, 1.0);
}

// soft wedge of light from the top, angled
float beam(vec2 q, float xTop, float xBottom, float halfW, float soft)
{
    float t = clamp((0.5 - q.y) / 1.0, 0.0, 1.0);          // 0 at top, 1 at bottom
    float cx = mix(xTop, xBottom, t);
    float w = halfW * (0.55 + 0.9 * t);                     // widens as it falls
    float d = abs(q.x - cx) / w;
    float fall = 1.0 - smoothstep(0.0, 1.0, t);             // dimmer near the floor
    return pow(max(0.0, 1.0 - d), soft) * fall;
}

void main()
{
    vec2 q = vec2((vUV.s - 0.5) * A, vUV.t - 0.5);
    float rev = clamp(uReveal, 0.0, 1.0);
    float light = 0.0;

    // --- broad beams: the main reason the space reads as a church
    light += 1.00 * beam(q, -0.62, -0.98, 0.080, 2.0);
    light += 0.80 * beam(q, -0.20, -0.44, 0.060, 2.2);
    light += 0.85 * beam(q,  0.18,  0.42, 0.060, 2.2);
    light += 0.95 * beam(q,  0.60,  0.96, 0.075, 2.0);
    light *= uBeams * (0.5 + 0.5 * rev);
    // the beams are the only thing that can show the air moving; keep it gentle
    float fog = fogField(vUV.st, uFog.y, uFog.z);
    light *= mix(1.0 - 0.22 * uFog.x, 1.0 + 0.40 * uFog.x, fog);

    // --- altar: a block catching the light, with a soft top face
    float ax = 0.17, atop = -0.055, abot = -0.135;
    float inAltar = step(abs(q.x), ax) * step(abot, q.y) * step(q.y, atop);
    float topFace = inAltar * smoothstep(atop - 0.035, atop, q.y);
    light += (0.16 + 0.22 * rev) * inAltar * 0.35;
    light += (0.16 + 0.24 * rev) * topFace;
    // two candles on the altar
    for (int i = 0; i < 2; i++) {
        vec2 c = vec2((i == 0 ? -1.0 : 1.0) * 0.105, atop + 0.045);
        light += (0.5 + 0.5 * rev) * 0.9 * exp(-length((q - c) * vec2(1.0, 0.55)) / 0.016);
        light += (0.3 + 0.4 * rev) * 0.25 * exp(-length(q - c) / 0.06);
    }

    // --- floor: two soft steps, no grid
    for (int i = 0; i < 3; i++) {
        float y = -0.155 - float(i) * 0.085;
        float halfw = 0.36 + float(i) * 0.26;                    // wider as it comes forward
        float edge = 1.0 - smoothstep(halfw * 0.82, halfw, abs(q.x));
        float band = edge * (1.0 - smoothstep(0.004, 0.030, abs(q.y - y)));
        light += (0.06 + 0.10 * rev) * band;
    }

    // --- cross, large and bright: the bloom pass downstream will spread it
    float cw = 0.020, cx = 0.0, cyb = 0.10, cyt = 0.42, arm = 0.115, ay = 0.335;
    float dc = min(segDist(q, vec2(cx, cyb), vec2(cx, cyt)), segDist(q, vec2(cx - arm, ay), vec2(cx + arm, ay)));
    float cross = 1.0 - smoothstep(cw * 0.5, cw * 1.25, dc);
    light += (0.30 + 0.35 * rev) * cross;
    light += (0.14 + 0.20 * rev) * exp(-dc / 0.05);          // halo around the cross

    // --- haze so the space has air in it. uFog.x = 0 reproduces the old flat
    // gradient exactly, so the toggle is a true A/B
    float vert = smoothstep(-0.5, 0.45, q.y);
    float floorBias = 1.0 + uFog.w * (1.0 - smoothstep(-0.5, -0.05, q.y));
    float haze = (0.02 + 0.03 * rev) * vert * floorBias
               * mix(1.0 - 0.55 * uFog.x, 1.0 + 0.85 * uFog.x, fog);
    light += haze;

    // air only shows where there IS light - scattering, not a grey wash. This is
    // what keeps the black floor black while the beams gain a drifting body.
    light += uFog.x * 0.30 * fog * smoothstep(0.015, 0.22, light);

    float v = clamp(light * uOpacity, 0.0, 1.5);
    fragColor = TDOutputSwizzle(vec4(vec3(v), clamp(v, 0.0, 1.0)));
}
