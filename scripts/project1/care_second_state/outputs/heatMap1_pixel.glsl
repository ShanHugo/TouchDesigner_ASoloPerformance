// S2 Heat Map x Temperature (teacher's visual plan, section 3)
// Three layers, heated in order: LOCAL (the parts doing the caring - chest,
// hands, head) leads while the room is still cold, then the BODY, and the ROOM
// only catches up as the act builds. Looked up in the 7-step thermal ramp
// (heatRampKeys1: cold navy -> blue -> teal -> green -> yellow -> orange -> white-hot)
// inputs: 0 Act 2 layer, 1 packed (r = soft body mask, g = Noise TOP), 2 thermal ramp
uniform float uHeat;       // effect_controller sceneHeat
uniform float uSubject;    // effect_controller subjectHeat
uniform float uLumWeight;  // how much bright elements (lights, table, crack) run hotter
uniform float uNoiseAmt;   // thermal-field variation
uniform vec3  uChest;      // chest x, y (uv, bottom-up), extra heat
uniform vec4  uHands;      // hands x, y, extra heat (0 when no hands), radius
uniform vec4  uHead;       // head x, y, extra heat, radius
uniform vec4  uZone;       // chest radius, local lead, room lag, unused
out vec4 fragColor;

float hotZone(vec2 uv, vec2 centre, float strength, float radius)
{
    if (strength <= 0.0 || radius <= 0.0) return 0.0;
    vec2 d = (uv - centre) * vec2(16.0 / 9.0, 1.0);
    return strength * exp(-dot(d, d) / (2.0 * radius * radius));
}

void main()
{
    vec2 uv = vUV.st;
    vec4 src = texture(sTD2DInputs[0], uv);
    vec4 mn = texture(sTD2DInputs[1], uv);
    float lum = dot(src.rgb, vec3(0.299, 0.587, 0.114));
    float mask = clamp(mn.r, 0.0, 1.0);
    float n = mn.g - 0.5;
    float heat = clamp(uHeat, 0.0, 1.0);

    // layer 3 - local: hands and head join the chest, and they run ahead of the
    // body while the act is still cold, so the caring itself is what glows first
    float local = hotZone(uv, uChest.xy, uChest.z, uZone.x)
                + hotZone(uv, uHands.xy, uHands.z, uHands.w)
                + hotZone(uv, uHead.xy,  uHead.z,  uHead.w);
    local *= mask * (1.0 + uZone.y * (1.0 - heat));
    // once the clouds have been pressed away the body should calm down too - a
    // lone hot spot left glowing after the release read as a leftover, not a state
    local *= uZone.w;

    // layer 1 - room: trails the cue while the act is cold, catches up at the burst
    float env = 0.88 * uHeat * mix(1.0 - uZone.z, 1.0, heat)
              + uLumWeight * lum + uNoiseAmt * n;
    // layer 2 - body: always a step warmer than the room so the figure stays readable
    float subj = uSubject + 0.05 + 0.5 * uLumWeight * lum + 0.5 * uNoiseAmt * n + local;
    float idx = clamp(mix(env, subj, mask), 0.0, 1.0);
    // sample texel centres only: u = 1.0 would wrap back to the cold end
    vec3 th = texture(sTD2DInputs[2], vec2(0.5 / 256.0 + idx * (255.0 / 256.0), 0.5)).rgb;
    fragColor = TDOutputSwizzle(vec4(th, 1.0));
}
