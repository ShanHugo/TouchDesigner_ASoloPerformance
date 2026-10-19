// S1 Depth Map x Bloom, grade pass (teacher's visual plan, section 2)
// Black-and-white only. Gray = half luminance + half max channel: plain luminance
// weights blue at 11%, which would make the blue/cyan Act 1 trigger effects
// (ripple, connector, ECG) all but vanish in grayscale.
// sceneReveal drives exposure and contrast: dark and flat at the start, brighter
// and more contrasted as the vow is "developed".
uniform float uReveal;   // effect_controller sceneReveal
uniform float uFloor;    // black floor (tuned so faint parts of trigger effects survive)
uniform float uVow;      // effect_controller vowBoost: hands joined at the chest (key moment)
out vec4 fragColor;
void main()
{
    vec3 c = texture(sTD2DInputs[0], vUV.st).rgb;
    float lum = dot(c, vec3(0.299, 0.587, 0.114));
    float mx = max(c.r, max(c.g, c.b));
    float g = 0.5 * lum + 0.5 * mx;
    // "low exposure" early = a gamma curve that sinks the darks/mids but leaves bright
    // elements at full strength - a flat multiply halved every trigger effect at the start
    // the vow lifts the highlights right away, even at the dark start of the act
    float gam = max(0.9, mix(1.7, 0.9, uReveal) - 0.8 * uVow);
    g = pow(clamp(g, 0.0, 1.0), gam);
    float expo = mix(1.0, 1.35, uReveal) + 0.25 * uVow;
    float con = mix(0.85, 1.25, uReveal);
    // black floor: the old deep-blue wash (max ~0.12) must read as near-black, not flat gray
    float floorv = uFloor;
    g = clamp((g * expo - floorv) / (1.0 - floorv), 0.0, 1.0);
    g = clamp((g - 0.3) * con + 0.3, 0.0, 1.0);
    fragColor = TDOutputSwizzle(vec4(vec3(g), 1.0));
}
