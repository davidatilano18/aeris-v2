'use strict';
// AERIS 3.0 · Narrativa de scroll (GSAP + ScrollTrigger + SplitText, locales).
// Sin GSAP, con movimiento reducido o al saltar, todo el contenido queda visible y estático.
(() => {
  const raiz = document.documentElement;
  if (!raiz.classList.contains('exp-inmersiva')) return;
  const atmosfera = () => window.AERIS_ATMOSFERA;
  const reducido = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const datos = document.getElementById('estado') || document.getElementById('panorama');

  // «Saltar animación»: detiene todo y lleva a los datos sin desplazamiento animado.
  function saltar() {
    raiz.classList.add('escena-saltada');
    raiz.classList.remove('escena-animada');
    if (window.ScrollTrigger) ScrollTrigger.getAll().forEach(t => t.kill(true));
    if (window.gsap) gsap.set('.aire-frase, .intro-contenido, .puerta, .escena-lienzo', {clearProps: 'all'});
    atmosfera()?.activo(false);
    document.querySelector('.escena-lienzo')?.setAttribute('hidden', '');
    datos?.scrollIntoView({behavior: 'auto', block: 'start'});
    datos?.querySelector('h2')?.setAttribute('tabindex', '-1');
    datos?.querySelector('h2')?.focus({preventScroll: true});
  }
  document.getElementById('saltarEscena')?.addEventListener('click', saltar);

  // «Pausar movimiento» (home.js) también detiene la atmósfera.
  const sincronizarPausa = () => atmosfera()?.activo(!document.body.classList.contains('motion-paused'));
  new MutationObserver(sincronizarPausa).observe(document.body, {attributes: true, attributeFilter: ['class']});

  if (reducido || !window.gsap || !window.ScrollTrigger) { raiz.classList.add('escena-estatica'); return; }
  gsap.registerPlugin(ScrollTrigger, ...(window.SplitText ? [SplitText] : []));
  raiz.classList.add('escena-animada');

  // Escena 1: el nombre aparece letra por letra; el resto entra después.
  const entrada = gsap.timeline({defaults: {ease: 'expo.out'}});
  const marca = document.querySelector('.intro-marca');
  document.fonts.ready.then(() => {
    if (window.SplitText && marca) {
      const letras = SplitText.create(marca, {type: 'chars', mask: 'chars', aria: 'auto'});
      entrada.from(letras.chars, {yPercent: 115, duration: 1.5, stagger: .085});
    }
    entrada.from('.intro-kicker', {y: 18, opacity: 0, duration: 1}, '-=1.2')
      .from('.intro-lema, .intro-acciones, .intro-dato', {y: 26, opacity: 0, duration: 1.1, stagger: .12}, '-=.9')
      .from('.intro-desliza', {opacity: 0, duration: .8}, '-=.5');
  });

  // Al bajar, la introducción sube y se desvanece (paralaje respecto al cielo).
  gsap.to('.intro-contenido', {yPercent: -28, opacity: 0, ease: 'none',
    scrollTrigger: {trigger: '.escena-intro', start: 'top top', end: 'bottom 15%', scrub: true}});

  // Profundidad de la cámara: de la portada hasta el inicio de los datos.
  ScrollTrigger.create({trigger: '.escena-intro', endTrigger: datos, start: 'top top', end: 'top bottom',
    onUpdate: s => atmosfera()?.profundidad(s.progress)});

  // Escena 2: fijada mientras pasan tres frases; la cámara desciende entre nubes.
  const frases = gsap.utils.toArray('.aire-frase');
  if (frases.length) {
    const tl = gsap.timeline({scrollTrigger: {trigger: '.escena-aire', start: 'top top',
      end: () => '+=' + Math.round(innerHeight * (innerWidth < 760 ? 1.8 : 2.4)), pin: true, scrub: .6, anticipatePin: 1}});
    frases.forEach((frase, i) => {
      tl.fromTo(frase, {opacity: 0, y: 40, filter: 'blur(6px)'}, {opacity: 1, y: 0, filter: 'blur(0px)', duration: 1, ease: 'power2.out'});
      if (i < frases.length - 1) tl.to(frase, {opacity: 0, y: -40, filter: 'blur(6px)', duration: .8, ease: 'power2.in'}, '+=.6');
      else tl.to({}, {duration: .6});
    });
  }

  // Escena 3: el cielo se aparta para que los datos sean lo principal; se apaga al salir.
  gsap.to('.escena-lienzo', {opacity: 0, ease: 'none',
    scrollTrigger: {trigger: datos, start: 'top 85%', end: 'top 20%', scrub: true,
      onLeave: () => atmosfera()?.visible(false), onEnterBack: () => atmosfera()?.visible(true)}});
  gsap.from('#estado .estado-verdict > *, #estado .estado-scale', {y: 30, opacity: 0, duration: .9, stagger: .08, ease: 'power3.out',
    scrollTrigger: {trigger: '#estado', start: 'top 70%', once: true}});

  // Escena 4: puertas y cifras reales (la animación termina exactamente en el valor publicado).
  gsap.from('.puerta', {y: 50, opacity: 0, duration: 1, stagger: .12, ease: 'power3.out',
    scrollTrigger: {trigger: '.puertas', start: 'top 75%', once: true}});
  document.querySelectorAll('[data-cifra]').forEach(nodo => {
    const final = Number(nodo.dataset.cifra);
    if (!Number.isFinite(final)) return;
    const obj = {v: 0};
    gsap.to(obj, {v: final, duration: 1.6, ease: 'power2.out', scrollTrigger: {trigger: nodo, start: 'top 85%', once: true},
      onUpdate: () => { nodo.textContent = Math.round(obj.v).toLocaleString('es-MX'); },
      onComplete: () => { nodo.textContent = final.toLocaleString('es-MX'); }});
  });

  // Las gráficas existentes cambian de tamaño al fijar secciones: recalcular al terminar de cargar.
  addEventListener('load', () => ScrollTrigger.refresh());
})();
