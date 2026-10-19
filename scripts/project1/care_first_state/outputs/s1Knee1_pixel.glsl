// S1 highlight soft-knee.
// The act brightens on purpose (sceneReveal and bloom both ramp with time), but
// by the end 20% of the cross region was pure white and 51% with hands joined -
// it read as glare, not as light. Everything below the knee is untouched; above
// it the response bends asymptotically toward 1.0 instead of clipping flat.
uniform vec4 uKnee;   // x = knee point, y = enable
out vec4 fragColor;

void main()
{
    vec4 c = texture(sTD2DInputs[0], vUV.st);
    vec3 v = c.rgb;
    if (uKnee.y > 0.5) {
        float k = clamp(uKnee.x, 0.05, 0.99);
        vec3 over = max(v - vec3(k), vec3(0.0));
        v = min(v, vec3(k)) + (1.0 - k) * (vec3(1.0) - exp(-over / max(1e-4, 1.0 - k)));
    }
    fragColor = TDOutputSwizzle(vec4(v, c.a));
}
