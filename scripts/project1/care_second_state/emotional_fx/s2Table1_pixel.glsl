// S2 table, redrawn to match the chairs' line work (the original was three rounded
// rectangles whose legs crossed through the table top). Same behaviour as before:
// uStretch (wearinessState1 table_transform) widens the table as the strain builds.
uniform float uTime;
uniform float uStretch;   // 0..1 weariness stretch
uniform float uOpacity;
uniform float uLine;      // line width, fraction of screen height
out vec4 fragColor;
const float A = 16.0 / 9.0;

float segDist(vec2 p, vec2 a, vec2 b)
{
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0);
    return length(pa - ba * h);
}

void main()
{
    vec2 q = vec2((vUV.s - 0.5) * A, vUV.t - 0.5);
    float s = pow(clamp(uStretch, 0.0, 1.0), 0.6);
    float W = 0.238 + (0.55 - 0.238) * s;          // half width, as before
    float LX = 0.098 + 0.142 * s;                   // leg x, as before
    float topY = 0.130, thick = 0.009;
    float farY = topY + 0.030, farIn = 0.055;       // far edge of the surface: depth
    float footY = -0.020;

    float d = 1e6;
    // near edge of the table top (a slab, not a rounded bar)
    d = min(d, segDist(q, vec2(-W, topY - thick), vec2(W, topY - thick)));
    d = min(d, segDist(q, vec2(-W, topY + thick), vec2(W, topY + thick)));
    d = min(d, segDist(q, vec2(-W, topY - thick), vec2(-W, topY + thick)));
    d = min(d, segDist(q, vec2(W, topY - thick), vec2(W, topY + thick)));
    // far edge, inset: reads as a surface with depth
    d = min(d, segDist(q, vec2(-W + farIn, farY), vec2(W - farIn, farY)));
    d = min(d, segDist(q, vec2(-W, topY + thick), vec2(-W + farIn, farY)));
    d = min(d, segDist(q, vec2(W, topY + thick), vec2(W - farIn, farY)));
    // apron just under the top
    d = min(d, segDist(q, vec2(-W * 0.93, topY - thick - 0.022), vec2(W * 0.93, topY - thick - 0.022)));
    // legs, slightly splayed, starting UNDER the top (no crossing lines)
    d = min(d, segDist(q, vec2(-LX, topY - thick), vec2(-LX - 0.012, footY)));
    d = min(d, segDist(q, vec2(LX, topY - thick), vec2(LX + 0.012, footY)));
    // small feet
    d = min(d, segDist(q, vec2(-LX - 0.026, footY), vec2(-LX + 0.004, footY)));
    d = min(d, segDist(q, vec2(LX - 0.004, footY), vec2(LX + 0.026, footY)));

    float m = 1.0 - smoothstep(uLine * 0.6, uLine * 1.6, d);
    vec3 col = vec3(0.85, 1.0, 0.6) * m * uOpacity;
    fragColor = TDOutputSwizzle(vec4(col, m * uOpacity));
}
