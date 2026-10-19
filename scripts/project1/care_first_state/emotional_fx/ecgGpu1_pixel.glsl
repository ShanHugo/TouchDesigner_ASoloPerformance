// S1 ECG trace, the drawing half of what ecgDraw1 used to do in PIL.
// Input 0 is ecgCurveTex1: N x 1, R = pulse value, G = valid flag, sample 0 at
// the left (oldest) and N-1 at the right (now). Per pixel we find the nearest
// segment of that polyline and shade it, which gives the same rounded joints
// and caps PIL's joint='curve' gave, with proper antialiasing and no per-frame
// readback.
uniform vec4 uGeom;    // xleft, xright, ybase, yrange
uniform vec4 uLine;    // baseWidthPx, brightness, beatBoost, beatWidthMul
uniform vec4 uMisc;    // peakRef, N, searchRadius, unused
out vec4 fragColor;

// same soft limit ecgDraw1 used: linear for small beats, compressing into the
// remaining canvas for big ones instead of clipping flat against the top
float curveY(float v)
{
    float ybase = uGeom.z;
    float yrange = uGeom.w;
    return ybase + 0.48 * (1.0 - exp(-2.2 * v * yrange));
}

vec2 samplePoint(float i, float N, vec2 res)
{
    float s = i / max(1.0, N - 1.0);
    vec2 texel = vec2((i + 0.5) / N, 0.5);
    float v = texture(sTD2DInputs[0], texel).r;
    float xf = uGeom.x + s * (uGeom.y - uGeom.x);     // TD offset space, -0.5..0.5
    return vec2((xf + 0.5) * res.x, (0.5 + curveY(v)) * res.y);
}

float sampleValue(float i, float N)
{
    return texture(sTD2DInputs[0], vec2((i + 0.5) / N, 0.5)).r;
}

float sampleValid(float i, float N)
{
    return texture(sTD2DInputs[0], vec2((i + 0.5) / N, 0.5)).g;
}

float segDist(vec2 p, vec2 a, vec2 b)
{
    vec2 ab = b - a;
    float denom = dot(ab, ab);
    float t = denom > 1e-6 ? clamp(dot(p - a, ab) / denom, 0.0, 1.0) : 0.0;
    return length(p - (a + ab * t));
}

void main()
{
    vec2 res = uTDOutputInfo.res.zw;
    vec2 px = vUV.st * res;
    float N = uMisc.y;
    // uMisc.z is kept for a tunable search radius; the fixed +-8 window below
    // already covers the widest beat at this line width

    // pixel x -> position along the scroll window -> nearest sample index
    float xf = vUV.s - 0.5;
    float s = (xf - uGeom.x) / max(1e-5, uGeom.y - uGeom.x);
    float fi = clamp(s * (N - 1.0), 0.0, N - 1.0);
    float i0 = floor(fi);

    float best = 1e9;
    float vlocal = 0.0;
    for (float k = -4.0; k <= 4.0; k += 1.0)
    {
        float ia = clamp(i0 + k, 0.0, N - 2.0);
        if (sampleValid(ia, N) < 0.5 || sampleValid(ia + 1.0, N) < 0.5) continue;
        vec2 a = samplePoint(ia, N, res);
        vec2 b = samplePoint(ia + 1.0, N, res);
        float d = segDist(px, a, b);
        if (d < best)
        {
            best = d;
            vlocal = max(sampleValue(ia, N), sampleValue(ia + 1.0, N));
        }
    }

    // per-segment brightness AND width from the local beat height, exactly as
    // ecgDraw1 did: a big beat flares and thickens, the resting line stays thin
    float norm = clamp(vlocal / max(0.05, uMisc.x), 0.0, 1.0);
    float w = uLine.x * (1.0 + (uLine.w - 1.0) * norm);
    float inten = clamp(uLine.y * (1.0 + uLine.z * norm), 0.0, 1.0);

    float cov = 1.0 - smoothstep(w * 0.5 - 0.75, w * 0.5 + 0.75, best);
    float lit = inten * cov;

    vec3 rgb = lit * vec3(1.2, 0.72, 0.55);
    float alpha = cov * step(0.002, inten);
    fragColor = TDOutputSwizzle(vec4(rgb, alpha));
}
