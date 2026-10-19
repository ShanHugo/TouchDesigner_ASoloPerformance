// Standby: the piece is waiting for the next visitor. Unity is showing its own
// "start" screen and sending 000, so this is the whole of what the audience
// outside sees. Deliberately almost nothing - the same cross as Act 1's church,
// far below that act's brightness, breathing slowly so the room can tell the
// installation is alive and not crashed.
//
// The geometry below is copied VERBATIM from s1Church1_pixel so the cross does
// not jump position or size the moment Act 1 starts.
uniform vec4 uStandby;   // x fade 0..1, y brightness, z breathe depth, w breathe seconds
uniform float uTime;
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

    float cw = 0.020, cx = 0.0, cyb = 0.10, cyt = 0.42, arm = 0.115, ay = 0.335;
    float dc = min(segDist(q, vec2(cx, cyb), vec2(cx, cyt)),
                   segDist(q, vec2(cx - arm, ay), vec2(cx + arm, ay)));
    float cross = 1.0 - smoothstep(cw * 0.5, cw * 1.25, dc);
    float halo  = exp(-dc / 0.07);

    // slow, never fully dark: a cross that blinks out would read as a fault
    float period = max(1.0, uStandby.w);
    float breathe = 1.0 - uStandby.z * (0.5 - 0.5 * cos(uTime * 6.28318530718 / period));

    float light = (cross * 0.55 + halo * 0.22) * uStandby.y * breathe;
    // the faintest floor gradient, so the frame reads as a dark room and not as
    // a broken signal
    light += 0.010 * smoothstep(-0.5, 0.5, q.y) * uStandby.y;

    float v = clamp(light * uStandby.x, 0.0, 1.0);
    vec3 col = v * vec3(1.0, 0.86, 0.70);   // warm, same family as the act's light

    // The halo is a very dark, very wide falloff, and 8-bit output quantises it
    // into visible stepped rings. A sub-LSB noise dither breaks the steps up;
    // without it the standby frame reads as banded garbage rather than a glow.
    float d = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
    col += (d - 0.5) / 255.0;

    fragColor = TDOutputSwizzle(vec4(max(col, 0.0), 1.0));
}
