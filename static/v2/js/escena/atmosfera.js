'use strict';
// AERIS 3.0 · Atmósfera en WebGL2: cielo con nubes (ruido fractal) y partículas en profundidad.
// Sin dependencias. Se detiene fuera de pantalla, baja de calidad si el equipo no da 30 fps
// y cae a un fondo estático (CSS) sin WebGL, con movimiento reducido o si se pierde el contexto.
(() => {
  const lienzo = document.getElementById('atmosfera');
  if (!lienzo) return;
  const raiz = document.documentElement;
  const estatica = motivo => { raiz.classList.add('atmosfera-estatica'); raiz.dataset.atmosfera = motivo; };
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return estatica('movimiento-reducido');
  const gl = lienzo.getContext('webgl2', {antialias: false, alpha: false, depth: false, stencil: false,
    powerPreference: 'low-power', preserveDrawingBuffer: false});
  if (!gl) return estatica('sin-webgl2');

  const modesto = (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4 ||
    innerWidth < 760 || (navigator.connection && navigator.connection.saveData);
  const NIVELES = [{escala: .5, octavas: 3, maximo: 900}, {escala: .75, octavas: 5, maximo: 3000}];
  let nivel = modesto ? 0 : 1;
  // Densidad pedida por la página: proporcional al promedio real de PM2.5 (ver data-particulas).
  const pedidas = Math.max(60, Number(lienzo.dataset.particulas) || 1200);

  const CIELO_V = `#version 300 es
  void main(){ vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2); gl_Position = vec4(p * 2. - 1., 0., 1.); }`;
  const CIELO_F = `#version 300 es
  precision highp float;
  uniform vec2 uRes; uniform float uTiempo, uProfundidad; uniform vec2 uCursor; uniform int uOctavas;
  out vec4 color;
  float azar(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
  float ruido(vec2 p){ vec2 i = floor(p), f = fract(p), u = f * f * (3. - 2. * f);
    return mix(mix(azar(i), azar(i + vec2(1, 0)), u.x), mix(azar(i + vec2(0, 1)), azar(i + vec2(1, 1)), u.x), u.y); }
  float fbm(vec2 p){ float v = 0., a = .5; mat2 r = mat2(.8, .6, -.6, .8);
    for (int i = 0; i < 6; i++) { if (i >= uOctavas) break; v += a * ruido(p); p = r * p * 2.02; a *= .5; } return v; }
  void main(){
    vec2 uv = gl_FragCoord.xy / uRes;
    vec2 p = (gl_FragCoord.xy - .5 * uRes) / uRes.y;
    float d = uProfundidad;
    // Cielo: noche azul arriba, horizonte turquesa que sube al descender.
    float horizonte = mix(.16, .62, d);
    vec3 arriba = vec3(.016, .047, .078), medio = vec3(.035, .12, .16), brillo = vec3(.16, .38, .41);
    vec3 cielo = mix(brillo, medio, smoothstep(horizonte - .28, horizonte + .18, uv.y));
    cielo = mix(cielo, arriba, smoothstep(horizonte + .1, 1.05, uv.y));
    // Nubes con deformación de dominio; crecen y envuelven al descender.
    float t = uTiempo * .012;
    vec2 q = p * mix(2.1, 5.2, d) + vec2(t * 3., d * 2.4);
    vec2 w = vec2(fbm(q + vec2(0., t)), fbm(q + vec2(5.2, 1.3 - t)));
    float n = fbm(q + 1.7 * w);
    float banda = smoothstep(-.15, .5 + .45 * d, 1. - uv.y + d * .65);
    float densidad = smoothstep(mix(.56, .36, d), .92, n) * banda;
    vec3 nube = mix(vec3(.42, .62, .68), vec3(.86, .95, .98), n);
    vec3 col = mix(cielo, nube, densidad * mix(.45, .62, d));
    col += .07 * exp(-7. * length(p - uCursor)) * vec3(.46, .94, .82);   // halo del cursor
    col *= .74 + .26 * smoothstep(1.35, .15, length(p));                   // viñeta
    color = vec4(col, 1.);
  }`;
  const PART_V = `#version 300 es
  in vec4 aSemilla;
  uniform float uTiempo, uProfundidad, uPixel; uniform vec2 uCursor; uniform float uAspecto;
  out float vAlfa;
  void main(){
    float z = fract(aSemilla.z - uProfundidad * 1.7 - uTiempo * .0035);   // la cámara avanza al descender
    float persp = 1. / (.14 + z * 1.55);
    vec2 deriva = .025 * vec2(sin(uTiempo * .21 + aSemilla.w * 6.283), cos(uTiempo * .17 + aSemilla.w * 4.1));
    vec2 pos = (aSemilla.xy + deriva) * persp * .55;
    vec2 cur = uCursor * vec2(1. / uAspecto, 1.) * 2.;
    vec2 dif = pos - cur; float r = length(dif);
    pos += dif / max(r, 1e-3) * .05 * exp(-r * r * 30.) * min(persp, 3.);   // las partículas se apartan del cursor
    gl_Position = vec4(pos, 0., 1.);
    gl_PointSize = uPixel * persp * (.55 + .9 * fract(aSemilla.w * 7.31));
    vAlfa = smoothstep(0., .12, z) * smoothstep(1., .55, z) * .6;
  }`;
  const PART_F = `#version 300 es
  precision mediump float;
  in float vAlfa; out vec4 color;
  void main(){ vec2 c = gl_PointCoord - .5; float a = exp(-dot(c, c) * 18.) * vAlfa;
    color = vec4(vec3(.82, 1., .95) * a, a); }`;

  function programa(v, f) {
    const p = gl.createProgram();
    for (const [tipo, src] of [[gl.VERTEX_SHADER, v], [gl.FRAGMENT_SHADER, f]]) {
      const s = gl.createShader(tipo); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      gl.attachShader(p, s);
    }
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    const u = {}; const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < n; i++) { const nombre = gl.getActiveUniform(p, i).name; u[nombre] = gl.getUniformLocation(p, nombre); }
    return {p, u};
  }

  let cielo, part, vao, buffer, cantidad = 0;
  try {
    cielo = programa(CIELO_V, CIELO_F);
    part = programa(PART_V, PART_F);
  } catch (error) {
    return estatica('shader');
  }
  vao = gl.createVertexArray();
  buffer = gl.createBuffer();

  function semillas() {
    cantidad = Math.min(pedidas, NIVELES[nivel].maximo);
    const datos = new Float32Array(cantidad * 4);
    let s = 1234567;  // generador determinista: misma escena en cada visita
    const azar = () => (s = (s * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < cantidad; i++) datos.set([azar() * 2 - 1, azar() * 2 - 1, azar(), azar()], i * 4);
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, datos, gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(part.p, 'aSemilla');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 4, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
  }

  let ancho = 0, alto = 0;
  function medir() {
    const dpr = Math.min(devicePixelRatio || 1, 1.5) * NIVELES[nivel].escala;
    ancho = Math.max(1, Math.round(innerWidth * dpr)); alto = Math.max(1, Math.round(innerHeight * dpr));
    if (lienzo.width !== ancho || lienzo.height !== alto) { lienzo.width = ancho; lienzo.height = alto; }
  }

  let profundidad = 0, cursor = [0, 0], cursorSuave = [0, 0], activo = true, visible = true;
  let cuadro = 0, inicio = performance.now(), muestras = [], ultimo = 0;

  function dibujar(ahora) {
    cuadro = 0;
    if (!activo || !visible || document.hidden) return;
    const t = (ahora - inicio) / 1000;
    cursorSuave[0] += (cursor[0] - cursorSuave[0]) * .06; cursorSuave[1] += (cursor[1] - cursorSuave[1]) * .06;
    gl.viewport(0, 0, ancho, alto);
    gl.disable(gl.BLEND);
    gl.useProgram(cielo.p);
    gl.uniform2f(cielo.u.uRes, ancho, alto); gl.uniform1f(cielo.u.uTiempo, t); gl.uniform1f(cielo.u.uProfundidad, profundidad);
    gl.uniform2f(cielo.u.uCursor, cursorSuave[0], cursorSuave[1]); gl.uniform1i(cielo.u.uOctavas, NIVELES[nivel].octavas);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);
    gl.useProgram(part.p);
    gl.uniform1f(part.u.uTiempo, t); gl.uniform1f(part.u.uProfundidad, profundidad);
    gl.uniform1f(part.u.uPixel, 2.4 * ancho / innerWidth);  // 2.4 px CSS base, en píxeles del lienzo
    gl.uniform2f(part.u.uCursor, cursorSuave[0], cursorSuave[1]); gl.uniform1f(part.u.uAspecto, ancho / alto);
    gl.bindVertexArray(vao); gl.drawArrays(gl.POINTS, 0, cantidad); gl.bindVertexArray(null);
    // Regulador: si el promedio supera ~33 ms por cuadro, baja un nivel de calidad una sola vez.
    if (ultimo) { muestras.push(ahora - ultimo); if (muestras.length > 90) muestras.shift(); }
    ultimo = ahora;
    if (nivel > 0 && muestras.length === 90 && muestras.reduce((a, b) => a + b) / 90 > 33) {
      nivel = 0; muestras = []; medir(); semillas(); raiz.dataset.atmosferaNivel = 'ligero';
    }
    pedir();
  }
  const pedir = () => { if (!cuadro && activo && visible && !document.hidden) { cuadro = requestAnimationFrame(dibujar); } };

  lienzo.addEventListener('webglcontextlost', e => { e.preventDefault(); activo = false; estatica('contexto-perdido'); });
  let espera;
  addEventListener('resize', () => { clearTimeout(espera); espera = setTimeout(medir, 120); }, {passive: true});
  document.addEventListener('visibilitychange', () => { ultimo = 0; pedir(); });
  if (matchMedia('(pointer: fine)').matches) {
    addEventListener('pointermove', e => {
      cursor = [(e.clientX - innerWidth / 2) / innerHeight, -(e.clientY - innerHeight / 2) / innerHeight];
    }, {passive: true});
  }

  medir(); semillas();
  raiz.dataset.atmosfera = 'webgl2';
  raiz.dataset.atmosferaNivel = nivel ? 'completo' : 'ligero';
  raiz.dataset.atmosferaParticulas = String(cantidad);
  pedir();

  // API mínima para la narrativa de scroll.
  window.AERIS_ATMOSFERA = {
    profundidad(v) { profundidad = Math.min(1, Math.max(0, v)); },
    activo(v) { activo = Boolean(v); ultimo = 0; muestras = []; if (activo) pedir(); else if (cuadro) { cancelAnimationFrame(cuadro); cuadro = 0; } },
    visible(v) { visible = Boolean(v); ultimo = 0; if (visible) pedir(); },
  };
})();
