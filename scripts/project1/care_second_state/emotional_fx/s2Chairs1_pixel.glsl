// S2 floating chairs (teacher's visual plan, section 3: "背景僅保留：桌面、漂浮的椅子、嘴")
// Side-view chair drawn as thin outline segments, same line look as the table icon.
// Each chair drifts and tilts slowly so the room reads as unmoored, not as a still life.
uniform float uTime;
uniform float uCount;    // how many chairs
uniform float uScale;    // chair size (fraction of screen height)
uniform float uOpacity;  // line brightness, matched to the table icon
uniform float uDrift;    // drift amount
uniform float uLine;     // line width as a fraction of screen height
out vec4 fragColor;
const float A = 16.0 / 9.0;

float hash1(float n) { return fract(sin(n * 127.1) * 43758.5453); }

float segDist(vec2 p, vec2 a, vec2 b)
{
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0);
    return length(pa - ba * h);
}

// chair outline in local units (seat at y=0, back to the left)
float chairMask(vec2 p, float w)
{
    float d = 1e6;
    d = min(d, segDist(p, vec2(-0.50, 0.00), vec2(0.50, 0.00)));   // seat
    d = min(d, segDist(p, vec2(-0.50, 0.00), vec2(-0.56, 0.95)));  // back post
    d = min(d, segDist(p, vec2(-0.56, 0.95), vec2(-0.20, 0.88)));  // back rail
    d = min(d, segDist(p, vec2(-0.20, 0.88), vec2(-0.16, 0.10)));  // back inner post
    d = min(d, segDist(p, vec2(0.44, 0.00), vec2(0.50, -0.80)));   // front leg
    d = min(d, segDist(p, vec2(-0.46, 0.00), vec2(-0.52, -0.80))); // back leg
    d = min(d, segDist(p, vec2(-0.49, -0.42), vec2(0.47, -0.42))); // rung
    return 1.0 - smoothstep(w * 0.6, w * 1.6, d);
}

void main()
{
    vec2 uv = vUV.st;
    vec2 q = vec2((uv.x - 0.5) * A, uv.y - 0.5);
    // fixed slots around the frame, well clear of the centre where the person is
    vec2 slots[8];
    slots[0] = vec2(-0.66,  0.30); slots[1] = vec2( 0.64,  0.26);
    slots[2] = vec2(-0.58, -0.06); slots[3] = vec2( 0.70, -0.10);
    slots[4] = vec2(-0.74,  0.10); slots[5] = vec2( 0.50,  0.36);
    slots[6] = vec2(-0.44,  0.38); slots[7] = vec2( 0.58,  0.06);
    float acc = 0.0;
    int n = int(clamp(uCount, 0.0, 8.0));
    for (int i = 0; i < 8; i++) {
        if (i >= n) break;
        float f = float(i);
        float ph = hash1(f + 7.0) * 6.2831;
        vec2 pos = slots[i] + uDrift * vec2(sin(uTime * (0.13 + 0.05 * hash1(f)) + ph),
                                            cos(uTime * (0.11 + 0.04 * hash1(f + 5.0)) + ph * 1.7));
        float rot = radians(12.0 * sin(uTime * 0.09 + ph) + 34.0 * (hash1(f + 2.0) - 0.5));
        float s = uScale * (0.85 + 0.35 * hash1(f + 13.0));
        vec2 d = (q - pos) / s;
        float c = cos(rot), si = sin(rot);
        d = mat2(c, -si, si, c) * d;
        acc = max(acc, chairMask(d, uLine / s));
    }
    vec3 col = vec3(0.85, 1.0, 0.6) * acc * uOpacity;
    fragColor = TDOutputSwizzle(vec4(col, acc * uOpacity));
}
