/**
 * GLSL for `liquid-chrome.tsx`, kept apart from the React code so the shader
 * reads and reviews as a shader. Plain strings, so no bundler loader is
 * needed.
 *
 * The fragment shader treats the screen as a sheet of liquid metal: a
 * domain-warped height field, its normal from finite differences, and a
 * reflection of a simple studio sky mapped onto the brand's steel, silver
 * and champagne. Dark parts stay transparent so the page's ink shows
 * through; only lit metal is drawn.
 */

export const LIQUID_CHROME_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

export const LIQUID_CHROME_FRAGMENT = /* glsl */ `
  precision highp float;
  varying vec2 vUv;
  uniform float uTime;
  uniform vec2 uRes;
  uniform vec2 uPointer;
  uniform vec3 uSteel;
  uniform vec3 uSilver;
  uniform vec3 uChampagne;
  uniform vec3 uMood;
  uniform float uMoodAmount;

  // Liquid height: a few rounds of sine warping. Smooth, cheap, and it
  // pools into the slow folds that read as poured metal.
  float height(vec2 p) {
    vec2 q = p;
    for (int i = 1; i < 7; i++) {
      float f = float(i);
      q += vec2(
        0.55 / f * sin(f * q.y + uTime * 0.22 + 0.3 * f + uPointer.x * 0.6),
        0.55 / f * cos(f * q.x + uTime * 0.17 + 0.5 * f + uPointer.y * 0.6)
      );
    }
    return 0.5 + 0.5 * sin(q.x * 1.1 + q.y * 0.9);
  }

  void main() {
    vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
    vec2 p = uv * 2.4 + vec2(0.0, uTime * 0.03);

    float e = 0.006;
    float h = height(p);
    float hx = height(p + vec2(e, 0.0));
    float hy = height(p + vec2(0.0, e));
    vec3 n = normalize(vec3(h - hx, h - hy, e * 5.0));

    // Reflect a sky that is bright overhead and dark at the floor.
    vec3 r = reflect(vec3(0.0, 0.0, -1.0), n);
    float sky = clamp(r.y * 0.5 + 0.5 + 0.18 * r.x, 0.0, 1.0);

    vec3 steelLow = uSteel * 0.55;
    vec3 steel = mix(steelLow, uMood, uMoodAmount);
    vec3 col = mix(vec3(0.0), steelLow, smoothstep(0.05, 0.45, sky));
    col = mix(col, steel, smoothstep(0.45, 0.65, sky));
    col = mix(col, uSilver, smoothstep(0.65, 0.85, sky));
    col = mix(col, uChampagne, smoothstep(0.86, 0.99, sky) * 0.85);

    // A key light that follows the pointer: the champagne highlight.
    vec3 light = normalize(vec3(0.35 + uPointer.x * 0.3, 0.55 + uPointer.y * 0.3, 1.0));
    float spec = pow(max(dot(n, light), 0.0), 60.0);
    col += uChampagne * spec * 0.9;

    // Deep folds fall into shadow.
    col *= 0.32 + 0.68 * smoothstep(0.0, 0.9, h);

    // Fade to the page at the edges and toward the bottom so copy stays legible.
    float vignette = smoothstep(1.25, 0.2, length(uv * vec2(0.8, 1.1)));
    float fadeBottom = smoothstep(0.0, 0.5, vUv.y);
    float lum = max(max(col.r, col.g), col.b);
    float alpha = clamp(lum * 1.15, 0.0, 1.0) * vignette * fadeBottom * 0.78;

    gl_FragColor = vec4(col * vignette * fadeBottom * 0.78, alpha);
  }
`;

/**
 * The same liquid metal clipped to a mask (the footer wordmark, owner,
 * 26 Nov 2026): `uMask` is the wordmark drawn white on transparent in a 2D
 * canvas, and only its alpha decides where metal shows. No vignette or
 * bottom fade; a floor of dim steel keeps the deepest folds readable as
 * letters.
 */
export const LIQUID_CHROME_MASKED_FRAGMENT = /* glsl */ `
  precision highp float;
  varying vec2 vUv;
  uniform float uTime;
  uniform vec2 uRes;
  uniform vec2 uPointer;
  uniform vec3 uSteel;
  uniform vec3 uSilver;
  uniform vec3 uChampagne;
  uniform sampler2D uMask;

  float height(vec2 p) {
    vec2 q = p;
    for (int i = 1; i < 7; i++) {
      float f = float(i);
      q += vec2(
        0.55 / f * sin(f * q.y + uTime * 0.22 + 0.3 * f + uPointer.x * 0.6),
        0.55 / f * cos(f * q.x + uTime * 0.17 + 0.5 * f + uPointer.y * 0.6)
      );
    }
    return 0.5 + 0.5 * sin(q.x * 1.1 + q.y * 0.9);
  }

  void main() {
    float mask = texture2D(uMask, vUv).a;
    if (mask < 0.004) discard;
    vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
    vec2 p = uv * 3.2 + vec2(uTime * 0.02, 0.0);

    float e = 0.006;
    float h = height(p);
    float hx = height(p + vec2(e, 0.0));
    float hy = height(p + vec2(0.0, e));
    vec3 n = normalize(vec3(h - hx, h - hy, e * 5.0));

    vec3 r = reflect(vec3(0.0, 0.0, -1.0), n);
    float sky = clamp(r.y * 0.5 + 0.5 + 0.18 * r.x, 0.0, 1.0);

    vec3 col = mix(uSteel * 0.3, uSteel * 0.7, smoothstep(0.1, 0.5, sky));
    col = mix(col, uSilver, smoothstep(0.55, 0.85, sky));
    col = mix(col, uChampagne, smoothstep(0.86, 0.99, sky) * 0.85);

    vec3 light = normalize(vec3(0.35 + uPointer.x * 0.6, 0.55 + uPointer.y * 0.6, 1.0));
    col += uChampagne * pow(max(dot(n, light), 0.0), 50.0) * 0.8;
    col *= 0.55 + 0.45 * smoothstep(0.0, 0.9, h);
    col = max(col, uSteel * 0.22);

    gl_FragColor = vec4(col * mask, mask);
  }
`;
