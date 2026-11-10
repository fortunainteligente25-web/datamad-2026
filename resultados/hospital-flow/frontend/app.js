/* Hospital Flow · frontend móvil (sin frameworks) */
'use strict';

(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

  // ------------------------------------------------------------------ utilidades
  function icono(nombre, clase = '') {
    return `<svg class="i ${clase}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ` +
      `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICONOS[nombre] || ''}</svg>`;
  }
  function pintarIconos(raiz = document) {
    $$('i[data-icon]', raiz).forEach(el => { el.outerHTML = icono(el.dataset.icon); });
  }
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const negritas = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  const km = v => Number(v).toFixed(1).replace('.', ',');
  const pct = v => String(v).replace('.', ',');
  const inicial = n => (String(n).trim()[0] || '?').toUpperCase();
  const fechaLocal = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const rutaCoche = h => `https://www.google.com/maps/dir/?api=1&destination=${h.lat},${h.lon}&travelmode=driving`;

  const almacen = {
    leer(clave, def) { try { const v = localStorage.getItem(clave); return v ? JSON.parse(v) : def; } catch { return def; } },
    guardar(clave, valor) { try { localStorage.setItem(clave, JSON.stringify(valor)); return true; } catch { return false; } },
  };

  async function api(ruta, opciones = {}) {
    const ctrl = new AbortController();
    const temporizador = setTimeout(() => ctrl.abort(), opciones.timeout || 20000);
    try {
      const r = await fetch(ruta, {
        method: opciones.method || 'GET',
        headers: opciones.body ? { 'Content-Type': 'application/json' } : undefined,
        body: opciones.body ? JSON.stringify(opciones.body) : undefined,
        signal: ctrl.signal,
      });
      const datos = await r.json().catch(() => ({}));
      if (!r.ok) {
        if (r.status === 422) throw new Error('Revisa los datos del formulario.');
        throw new Error(typeof datos.detail === 'string' ? datos.detail : 'Error del servidor.');
      }
      return datos;
    } finally {
      clearTimeout(temporizador);
    }
  }

  let temporizadorToast;
  function toast(texto) {
    const el = $('.toast');
    el.textContent = texto;
    el.hidden = false;
    clearTimeout(temporizadorToast);
    temporizadorToast = setTimeout(() => { el.hidden = true; }, 3200);
  }

  function normalizarTel(t) {
    let s = String(t || '').replace(/[^\d+]/g, '');
    if (s.startsWith('00')) s = '+' + s.slice(2);
    if (/^[6789]\d{8}$/.test(s)) s = '+34' + s;
    else if (/^34[6789]\d{8}$/.test(s)) s = '+' + s;
    return /^\+\d{8,15}$/.test(s) ? s : null;
  }
  function verTel(e164) {
    const m = /^\+34(\d{3})(\d{2})(\d{2})(\d{2})$/.exec(e164);
    return m ? `${m[1]} ${m[2]} ${m[3]} ${m[4]}` : e164;
  }

  // ------------------------------------------------------------------ estado
  const estado = {
    ubicacion: null,          // { lat, lon, nombre, origen: 'gps' | 'zona' }
    zonas: [],
    resultado: null,          // respuesta de /api/recomendar
    seleccionado: 0,          // hospital elegido dentro del resultado
    explicacion: null,        // null = cargando · '' = no disponible
    contactos: almacen.leer('hf_contactos', []),
    hospitales: null,
    mapa: null,
    mapaAjustado: false,
    filtroCitas: 'activas',
  };

  // ------------------------------------------------------------------ navegación
  const VISTAS = ['inicio', 'resultado', 'mapa', 'citas', 'contactos'];
  function mostrar() {
    let vista = (location.hash || '#inicio').slice(1);
    if (!VISTAS.includes(vista)) vista = 'inicio';
    if (vista === 'resultado' && !estado.resultado) {
      vista = 'inicio';
      history.replaceState(null, '', '#inicio');
    }
    cerrarHoja();
    document.body.classList.toggle('en-mapa', vista === 'mapa');
    VISTAS.forEach(n => { $('#v-' + n).hidden = n !== vista; });
    const pestana = vista === 'resultado' ? 'inicio' : vista;
    $$('.tabbar a').forEach(a => {
      if (a.dataset.tab === pestana) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    window.scrollTo(0, 0);
    if (vista === 'mapa') abrirMapa();
    if (vista === 'citas') pintarCitas();
    if (vista === 'contactos') pintarContactos();
  }

  // ------------------------------------------------------------------ ubicación
  async function cargarZonas() {
    try {
      estado.zonas = await api('/api/zonas');
    } catch {
      estado.zonas = [{ nombre: 'Puerta del Sol', lat: 40.4168, lon: -3.7038 }];
    }
    const sel = $('#zona');
    sel.innerHTML = estado.zonas.map((z, i) => `<option value="${i}">${esc(z.nombre)}</option>`).join('');
    const guardada = Number(almacen.leer('hf_zona', 0));
    sel.value = String(guardada < estado.zonas.length ? guardada : 0);
    elegirZona();
    // Si el usuario ya dio permiso de ubicación antes, se usa el GPS sin preguntar.
    try {
      const permiso = await navigator.permissions?.query({ name: 'geolocation' });
      if (permiso && permiso.state === 'granted') usarGPS(true);
    } catch { /* sin API de permisos */ }
  }

  function elegirZona() {
    const sel = $('#zona');
    if (sel.value === 'gps') return;
    const z = estado.zonas[Number(sel.value)] || estado.zonas[0];
    estado.ubicacion = { lat: z.lat, lon: z.lon, nombre: z.nombre, origen: 'zona' };
    almacen.guardar('hf_zona', Number(sel.value));
    $('#btn-gps span').textContent = 'Usar GPS';
  }

  function usarGPS(silencioso = false) {
    const btn = $('#btn-gps');
    if (!('geolocation' in navigator) || !window.isSecureContext) {
      if (!silencioso) toast('El GPS necesita abrir la app con https. Elige tu zona.');
      return;
    }
    btn.disabled = true;
    btn.querySelector('span').textContent = 'Buscando…';
    navigator.geolocation.getCurrentPosition(pos => {
      estado.ubicacion = { lat: pos.coords.latitude, lon: pos.coords.longitude, nombre: 'Tu ubicación', origen: 'gps' };
      const sel = $('#zona');
      if (!sel.querySelector('option[value="gps"]')) sel.insertAdjacentHTML('afterbegin', '<option value="gps">Tu ubicación (GPS)</option>');
      sel.value = 'gps';
      btn.disabled = false;
      btn.querySelector('span').textContent = 'GPS activo';
      estado.mapaAjustado = false;
      if (!silencioso) toast('Ubicación actualizada');
    }, err => {
      btn.disabled = false;
      btn.querySelector('span').textContent = 'Usar GPS';
      if (!silencioso) {
        toast(err.code === 1 ? 'Sin permiso de ubicación. Elige tu zona.' : 'No hemos podido ubicarte. Elige tu zona.');
        $('#zona').focus();
      }
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  }

  // ------------------------------------------------------------------ búsqueda
  async function buscar(e) {
    e.preventDefault();
    const mensaje = $('#mensaje').value.trim();
    if (mensaje.length < 3) {
      toast('Cuéntanos un poco qué te pasa.');
      $('#mensaje').focus();
      return;
    }
    if (!estado.ubicacion) elegirZona();
    const btn = $('#btn-buscar');
    btn.disabled = true;
    btn.innerHTML = icono('loader-circle', 'girando') + '<span>Analizando…</span>';
    try {
      const r = await api('/api/recomendar', {
        method: 'POST',
        body: { mensaje, lat: estado.ubicacion.lat, lon: estado.ubicacion.lon },
      });
      estado.resultado = r;
      estado.seleccionado = 0;
      estado.explicacion = null;
      pintarResultado();
      if (location.hash !== '#resultado') location.hash = '#resultado';
      else mostrar();
      if (r.triaje.nivel !== 'emergencia' && r.hospitales.length) cargarExplicacion(r);
    } catch {
      toast('No hemos podido conectar. Inténtalo de nuevo.');
    } finally {
      btn.disabled = false;
      btn.innerHTML = icono('search') + '<span>Buscar hospital</span>';
    }
  }

  async function cargarExplicacion(r) {
    try {
      const e = await api('/api/explicar', {
        method: 'POST',
        timeout: 15000,
        body: { nivel: r.triaje.nivel, especialidad: r.triaje.especialidad, modo: r.modo, hospitales: r.hospitales },
      });
      if (estado.resultado !== r) return;
      estado.explicacion = e.texto || '';
    } catch {
      if (estado.resultado !== r) return;
      estado.explicacion = '';
    }
    const p = $('#explicacion');
    if (!p) return;
    if (estado.explicacion) p.textContent = estado.explicacion;
    else p.closest('.porque').remove();
  }

  // ------------------------------------------------------------------ resultado
  const BANNER = {
    urgente: { clase: 'banner-urgente', icono: 'triangle-alert', titulo: 'Conviene que te vea un médico hoy' },
    leve: { clase: 'banner-leve', icono: 'info', titulo: 'No parece urgente' },
    programada: { clase: 'banner-programada', icono: 'calendar-days', titulo: 'Operación programada' },
  };

  function pintarResultado() {
    const r = estado.resultado;
    const t = r.triaje;
    const cont = $('#v-resultado');
    const volver = `<button type="button" class="volver" data-accion="volver">${icono('chevron-left')}Nueva consulta</button>`;

    if (t.crisis) { cont.innerHTML = volver + vistaCrisis(t); return; }
    if (t.nivel === 'emergencia') { cont.innerHTML = volver + vistaEmergencia(); return; }
    if (!r.hospitales.length) {
      cont.innerHTML = volver + '<div class="card"><p>No hay hospitales disponibles ahora mismo.</p></div>';
      return;
    }

    const b = BANNER[t.nivel] || BANNER.leve;
    const etiquetas = [t.especialidad, t.procedimiento].filter(Boolean)
      .map(x => `<span class="etiqueta">${esc(x)}</span>`).join('');
    cont.innerHTML = `
      ${volver}
      <div class="banner ${b.clase}">${icono(b.icono)}<div><span class="banner-titulo"><strong>${b.titulo}</strong></span><p>${negritas(t.mensaje)}</p></div></div>
      ${etiquetas ? `<div class="etiquetas">${etiquetas}</div>` : ''}
      ${r.fuera_de_madrid ? '<p class="nota">Parece que no estás en Madrid: estos hospitales son de la Comunidad de Madrid.</p>' : ''}
      ${tarjetaHospital(r.hospitales[estado.seleccionado], r, t)}
      ${alternativas(r)}
      <p class="nota">Ocupación y esperas simuladas · Es una orientación, no un diagnóstico.</p>`;
  }

  function tarjetaHospital(h, r, t) {
    const programada = r.modo === 'programada';
    const recomendado = estado.seleccionado === 0;
    const nivelOcc = String(h.nivel_ocupacion).toLowerCase();

    const metricas = programada ? `
        <div class="metrica"><span class="m-etiqueta">Distancia</span><span class="m-valor">${km(h.distancia_km)} km</span><span class="m-sub">${h.viaje_min} min en coche</span></div>
        <div class="metrica"><span class="m-etiqueta">Lista de espera</span><span class="m-valor">${h.demora_dias != null ? Math.round(h.demora_dias) + ' días' : '—'}</span><span class="m-sub">${h.demora_dias != null ? 'de media' : 'aún sin datos oficiales'}</span></div>`
      : `
        <div class="metrica"><span class="m-etiqueta">Espera</span><span class="m-valor">${h.espera_min} min</span><span class="m-sub">estimada</span></div>
        <div class="metrica"><span class="m-etiqueta">Llegas en</span><span class="m-valor">${h.viaje_min} min</span><span class="m-sub">${km(h.distancia_km)} km</span></div>
        <div class="metrica"><span class="m-etiqueta">Ocupación</span><span class="m-valor"><i class="dot dot-${esc(nivelOcc)}"></i>${esc(h.nivel_ocupacion)}</span><span class="m-sub">${pct(h.ocupacion_pct)} %</span></div>`;

    const especialidad = t.especialidad ? (h.tiene_especialidad
      ? `<p class="esp si">${icono('circle-check')}Tiene ${esc(t.especialidad)}</p>`
      : `<p class="esp no">${icono('info')}Sin ${esc(t.especialidad)}: te atienden en urgencias generales</p>`) : '';

    const porque = recomendado && estado.explicacion !== '' ? `
        <div class="porque"><h3>Por qué</h3>
          <p id="explicacion">${estado.explicacion ? esc(estado.explicacion) : '<span class="cargando-texto" style="display:block" aria-label="Cargando explicación"></span>'}</p>
        </div>` : '';

    const acciones = programada ? `
        <button type="button" class="btn btn-primary btn-block" data-accion="nueva-cita">${icono('calendar-days')}Pedir cita aquí</button>
        <a class="btn btn-secondary btn-block" href="${rutaCoche(h)}" target="_blank" rel="noopener">${icono('navigation')}Cómo llegar</a>`
      : `
        <a class="btn btn-primary btn-block" href="${rutaCoche(h)}" target="_blank" rel="noopener">${icono('navigation')}Cómo llegar</a>
        <div class="btn-row">
          <button type="button" class="btn btn-secondary" data-accion="taxi">${icono('car-taxi-front')}Pedir taxi</button>
          <button type="button" class="btn btn-secondary" data-accion="avisar" aria-label="Avisar a alguien">${icono('message-circle')}Avisar</button>
        </div>`;

    return `
      <article class="card hosp">
        <div>
          <span class="eyebrow">${recomendado ? 'Te recomendamos' : 'Otra opción'}</span>
          <h2>${esc(h.nombre)}</h2>
          <p class="dir">${esc(h.direccion)}</p>
        </div>
        <div class="metricas${programada ? ' dos' : ''}">${metricas}</div>
        ${especialidad}
        ${porque}
        ${acciones}
      </article>`;
  }

  function alternativas(r) {
    const otras = r.hospitales.map((h, i) => ({ h, i })).filter(x => x.i !== estado.seleccionado);
    if (!otras.length) return '';
    const programada = r.modo === 'programada';
    const titulo = otras.length === 1 ? 'Ver otra opción' : `Ver otras ${otras.length} opciones`;
    const filas = otras.map(({ h, i }) => `
        <div class="alt">
          <div class="alt-info">
            <strong>${esc(h.nombre)}${i === 0 ? ' · recomendado' : ''}</strong>
            <span>${programada
              ? `${km(h.distancia_km)} km · ${h.viaje_min} min en coche`
              : `Espera ${h.espera_min} min · ${h.viaje_min} min en coche · ocupación ${esc(String(h.nivel_ocupacion).toLowerCase())}`}</span>
          </div>
          <button type="button" class="btn btn-outline btn-sm" data-accion="elegir" data-i="${i}">Ver</button>
        </div>`).join('');
    return `<details class="alternativas"><summary>${titulo}${icono('chevron-down')}</summary>${filas}</details>`;
  }

  function vistaEmergencia() {
    return `
      <div class="emergencia" role="alert">
        <div class="em-icono">${icono('siren')}</div>
        <h1>Puede ser una emergencia</h1>
        <p>Llama al <strong>112</strong> ahora y sigue sus instrucciones. No conduzcas tú hasta el hospital.</p>
        <a class="btn btn-blanco btn-xl btn-block" href="tel:112">${icono('phone')}Llamar al 112</a>
        <button type="button" class="btn btn-borde-blanco btn-block" data-accion="avisar">${icono('message-circle')}Avisar a alguien</button>
      </div>
      <p class="nota">Es una orientación automática, no un diagnóstico.</p>`;
  }

  function vistaCrisis(t) {
    return `
      <div class="card crisis" role="alert">
        <span class="em-icono">${icono('heart-handshake', 'i-grande')}</span>
        <h1>Hay gente que puede ayudarte</h1>
        <p>${negritas(t.mensaje)}</p>
        <a class="btn btn-primary btn-xl btn-block" href="tel:024">${icono('phone')}Llamar al 024</a>
        <p class="peque">Atención a la conducta suicida · gratuita · 24 horas</p>
        <a class="btn btn-danger btn-block" href="tel:112">${icono('phone')}Si estás en peligro ahora: 112</a>
        <button type="button" class="btn btn-secondary btn-block" data-accion="avisar">${icono('message-circle')}Avisar a alguien de confianza</button>
      </div>`;
  }

  // ------------------------------------------------------------------ hojas inferiores
  let focoPrevio = null;
  function abrirHoja(html, alMontar) {
    if ($('.sheet').hidden) focoPrevio = document.activeElement;
    const hoja = $('.sheet');
    const cuerpo = $('.sheet-cuerpo');
    cuerpo.innerHTML = html;
    $('.sheet-fondo').hidden = false;
    hoja.hidden = false;
    hoja.scrollTop = 0;
    document.body.style.overflow = 'hidden';
    if (alMontar) alMontar(cuerpo);
    hoja.setAttribute('tabindex', '-1');
    hoja.focus({ preventScroll: true });
  }
  function cerrarHoja() {
    const hoja = $('.sheet');
    if (hoja.hidden) return;
    hoja.hidden = true;
    $('.sheet-fondo').hidden = true;
    document.body.style.overflow = '';
    if (focoPrevio && focoPrevio.isConnected) focoPrevio.focus({ preventScroll: true });
  }

  // Taxi
  async function hojaTaxi() {
    const h = estado.resultado.hospitales[estado.seleccionado];
    const decir = `${h.nombre}, ${h.direccion}`;
    abrirHoja(`
      <h2 id="sheet-titulo">Pedir taxi</h2>
      <div class="card-lite destino">
        <div><span class="eyebrow">Dile al taxista</span><p><strong>${esc(h.nombre)}</strong><br>${esc(h.direccion)}</p></div>
        <button type="button" class="icon-btn" data-accion="copiar" data-texto="${esc(decir)}" aria-label="Copiar destino">${icono('copy')}</button>
      </div>
      <div><h3>Llama a una emisora</h3>
        <ul class="lista" id="lista-emisoras" style="margin-top:8px"><li class="cargando-texto"></li></ul></div>
      <div id="bloque-paradas"></div>
      <p class="nota" id="fuente-emisoras"></p>`);
    try {
      const u = estado.ubicacion;
      const d = await api(`/api/taxis?lat=${u.lat}&lon=${u.lon}`);
      $('#lista-emisoras').innerHTML = d.emisoras.map(em => `
        <li><a class="fila fila-llamada" href="tel:${esc(em.telefono)}">
          <span class="icono-redondo">${icono('phone')}</span>
          <span class="fila-info"><strong>${esc(em.nombre)}</strong><span>${esc(em.visible)}${em.nota ? ' · ' + esc(em.nota) : ''}</span></span>
        </a></li>`).join('');
      if (d.paradas.length) {
        const p = d.paradas[0];
        $('#bloque-paradas').innerHTML = `<h3>Parada más cercana</h3>
          <a class="fila" style="margin-top:8px" target="_blank" rel="noopener"
             href="https://www.google.com/maps/dir/?api=1&destination=${p.lat},${p.lon}&travelmode=walking">
            ${icono('footprints')}
            <span class="fila-info"><strong>${esc(p.nombre)}</strong>
              <span>${p.distancia_m} m · ${p.a_pie_min} min a pie${p.horario ? ' · ' + esc(p.horario) : ''}</span></span>
            ${icono('chevron-right')}
          </a>`;
      }
      $('#fuente-emisoras').textContent = `${d.fuente_emisoras}.`;
    } catch {
      $('#lista-emisoras').innerHTML = '<li class="muted">No se han podido cargar los teléfonos.</li>';
    }
  }

  async function copiar(texto) {
    try {
      await navigator.clipboard.writeText(texto);
      toast('Copiado');
    } catch {
      const ta = document.createElement('textarea');
      ta.value = texto;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); toast('Copiado'); } catch { toast('No se ha podido copiar'); }
      ta.remove();
    }
  }

  // Avisar a alguien
  function textoAviso() {
    const r = estado.resultado;
    const u = estado.ubicacion;
    const mapa = u ? ` Mi ubicación: https://maps.google.com/?q=${u.lat.toFixed(5)},${u.lon.toFixed(5)}` : '';
    if (!r) return `¿puedes llamarme cuando puedas?${mapa}`;
    if (r.triaje.crisis) return `¿puedes llamarme o venir? Te necesito.${mapa}`;
    if (r.triaje.nivel === 'emergencia') return `tengo una emergencia y estoy llamando al 112.${mapa}`;
    const h = r.hospitales[estado.seleccionado];
    return `voy al ${h.nombre} (${h.direccion}).${mapa}`;
  }

  function enlaceCanal(canal, c, cuerpo) {
    const texto = `Hola ${String(c.nombre).split(' ')[0]}, ${cuerpo.trim()}`;
    if (canal === 'tel') return `tel:${c.telefono}`;
    if (canal === 'wa') return `https://wa.me/${c.telefono.replace('+', '')}?text=${encodeURIComponent(texto)}`;
    return `sms:${c.telefono}?&body=${encodeURIComponent(texto)}`;
  }

  function vacioContactos() {
    return `
      <div class="vacio card-lite">
        <span class="icono-vacio">${icono('user-plus')}</span>
        <p><strong>Aún no tienes contactos de confianza</strong></p>
        <p class="muted">Añade hasta 3 personas para avisarles en un toque.</p>
        <button type="button" class="btn btn-primary" data-accion="nuevo-contacto">${icono('user-plus')}Añadir contacto</button>
      </div>`;
  }

  function hojaAvisar() {
    const lista = estado.contactos;
    const filas = lista.map((c, i) => `
      <li class="card-lite contacto-aviso">
        <div class="fila-nombre"><span class="avatar">${esc(inicial(c.nombre))}</span>
          <span class="contacto-info"><strong>${esc(c.nombre)}</strong><span>${esc(c.relacion)} · ${esc(verTel(c.telefono))}</span></span></div>
        <div class="tres">
          <a class="btn btn-secondary accion-v" data-canal="tel" data-i="${i}" href="#">${icono('phone')}Llamar</a>
          <a class="btn btn-secondary accion-v" data-canal="wa" data-i="${i}" href="#" target="_blank" rel="noopener">${icono('message-circle')}WhatsApp</a>
          <a class="btn btn-secondary accion-v" data-canal="sms" data-i="${i}" href="#">${icono('message-square-text')}SMS</a>
        </div>
      </li>`).join('');
    abrirHoja(`
      <h2 id="sheet-titulo">Avisar a alguien</h2>
      <div class="campo">
        <label for="txt-aviso">Mensaje</label>
        <textarea id="txt-aviso" rows="3" maxlength="400">${esc(textoAviso())}</textarea>
        <p class="mensaje-previo">Se envía empezando por «Hola» y su nombre.</p>
      </div>
      ${lista.length ? `<ul class="lista">${filas}</ul>` : vacioContactos()}
      ${lista.length && lista.length < 3 ? `<button type="button" class="btn btn-ghost btn-block" data-accion="nuevo-contacto">${icono('user-plus')}Añadir otro contacto</button>` : ''}`,
    cuerpo => {
      const ta = cuerpo.querySelector('#txt-aviso');
      const actualizar = () => cuerpo.querySelectorAll('[data-canal]').forEach(a => {
        a.href = enlaceCanal(a.dataset.canal, estado.contactos[Number(a.dataset.i)], ta.value);
      });
      ta.addEventListener('input', actualizar);
      actualizar();
    });
  }

  // Contactos
  const RELACIONES = ['Familiar', 'Pareja', 'Amigo/a', 'Compañero/a', 'Otro'];
  const hayAgenda = () => 'contacts' in navigator && typeof navigator.contacts?.select === 'function';

  function hojaContacto(prellenado = {}, alGuardar = null) {
    abrirHoja(`
      <h2 id="sheet-titulo">Nuevo contacto</h2>
      ${hayAgenda() ? `<button type="button" class="btn btn-secondary btn-block" id="btn-agenda">${icono('contact-round')}Elegir de mis contactos</button>` : ''}
      <form class="form" id="f-contacto" novalidate>
        <div class="campo"><label for="c-nombre">Nombre</label>
          <input id="c-nombre" autocomplete="name" maxlength="40" placeholder="Ej.: Mamá" value="${esc(prellenado.nombre || '')}"></div>
        <div class="campo"><label for="c-tel">Teléfono</label>
          <input id="c-tel" type="tel" inputmode="tel" autocomplete="tel" maxlength="20" placeholder="600 11 22 33" value="${esc(prellenado.telefono || '')}"></div>
        <div class="campo"><label for="c-rel">Relación</label>
          <select id="c-rel">${RELACIONES.map(r => `<option>${r}</option>`).join('')}</select></div>
        <button type="submit" class="btn btn-primary btn-block">${icono('check')}Guardar</button>
      </form>
      <p class="nota">Se guarda solo en este móvil.</p>`,
    cuerpo => {
      cuerpo.querySelector('#btn-agenda')?.addEventListener('click', () => elegirDeAgenda(alGuardar));
      cuerpo.querySelector('#f-contacto').addEventListener('submit', e => { e.preventDefault(); guardarContacto(alGuardar); });
    });
  }

  async function elegirDeAgenda(alGuardar) {
    try {
      const [c] = await navigator.contacts.select(['name', 'tel'], { multiple: false });
      if (c) hojaContacto({ nombre: (c.name && c.name[0]) || '', telefono: (c.tel && c.tel[0]) || '' }, alGuardar);
    } catch {
      toast('No se ha podido abrir tu agenda.');
    }
  }

  function guardarContacto(alGuardar) {
    const nombre = $('#c-nombre').value.trim();
    const telefono = normalizarTel($('#c-tel').value);
    if (!nombre) { toast('Escribe un nombre.'); $('#c-nombre').focus(); return; }
    if (!telefono) { toast('Revisa el teléfono (ej.: 600 11 22 33).'); $('#c-tel').focus(); return; }
    if (estado.contactos.length >= 3) { toast('Máximo 3 contactos.'); return; }
    estado.contactos.push({ nombre, telefono, relacion: $('#c-rel').value });
    toast(almacen.guardar('hf_contactos', estado.contactos) ? 'Contacto guardado' : 'Guardado solo mientras la app esté abierta');
    cerrarHoja();
    if (typeof alGuardar === 'function') alGuardar();
    if (!$('#v-contactos').hidden) pintarContactos();
  }

  function pintarContactos() {
    const lista = estado.contactos;
    const filas = lista.map((c, i) => `
      <li class="contacto">
        <span class="avatar">${esc(inicial(c.nombre))}</span>
        <span class="contacto-info"><strong>${esc(c.nombre)}</strong><span>${esc(c.relacion)} · ${esc(verTel(c.telefono))}</span></span>
        <span class="acciones">
          <a class="icon-btn" href="tel:${esc(c.telefono)}" aria-label="Llamar a ${esc(c.nombre)}">${icono('phone')}</a>
          <button type="button" class="icon-btn neutro" data-accion="borrar-contacto" data-i="${i}" aria-label="Borrar a ${esc(c.nombre)}">${icono('trash-2')}</button>
        </span>
      </li>`).join('');
    $('#v-contactos').innerHTML = `
      <h1 id="t-contactos">Contactos de confianza</h1>
      <p class="sub">Para avisarles en un toque si vas al hospital. Se guardan solo en este móvil.</p>
      ${lista.length ? `<ul class="lista">${filas}</ul>` : vacioContactos()}
      ${lista.length && lista.length < 3 ? `<button type="button" class="btn btn-secondary btn-block" data-accion="nuevo-contacto">${icono('user-plus')}Añadir contacto</button>` : ''}
      ${lista.length >= 3 ? '<p class="nota">Has llegado al máximo de 3 contactos.</p>' : ''}`;
  }

  function borrarContacto(i, boton) {
    if (boton.dataset.confirmar !== '1') {
      boton.dataset.confirmar = '1';
      boton.classList.replace('neutro', 'peligro');
      toast('Pulsa otra vez para borrar');
      setTimeout(() => { if (boton.isConnected) { boton.dataset.confirmar = ''; boton.classList.replace('peligro', 'neutro'); } }, 3000);
      return;
    }
    estado.contactos.splice(i, 1);
    almacen.guardar('hf_contactos', estado.contactos);
    pintarContactos();
    toast('Contacto borrado');
  }

  // ------------------------------------------------------------------ citas
  async function hospitalesParaCita() {
    if (!estado.hospitales) {
      try { estado.hospitales = (await api('/api/hospitales')).hospitales; } catch { estado.hospitales = []; }
    }
    const r = estado.resultado;
    if (!r) return estado.hospitales;
    const ids = r.hospitales.map(h => h.id);
    return [...r.hospitales, ...estado.hospitales.filter(h => !ids.includes(h.id))];
  }

  async function pintarCitas() {
    const cont = $('#v-citas');
    const activas = estado.filtroCitas === 'activas';
    cont.innerHTML = `
      <h1 id="t-citas">Citas</h1>
      <div class="segmentado" role="group" aria-label="Filtrar citas">
        <button type="button" data-accion="filtro-citas" data-valor="activas" aria-pressed="${activas}">Activas</button>
        <button type="button" data-accion="filtro-citas" data-valor="canceladas" aria-pressed="${!activas}">Canceladas</button>
      </div>
      <div id="lista-citas" class="lista"><div class="cargando-texto"></div></div>
      <button type="button" class="btn btn-primary btn-block" data-accion="nueva-cita">${icono('plus')}Nueva cita</button>
      <p class="nota">Simulación: las citas no se envían a ningún hospital.</p>`;
    let citas;
    try { citas = await api('/api/citas'); } catch {
      $('#lista-citas').innerHTML = '<p class="muted">No se han podido cargar las citas.</p>';
      return;
    }
    const lista = citas.filter(c => (c.estado === 'Confirmada') === activas);
    $('#lista-citas').innerHTML = lista.length ? lista.map(tarjetaCita).join('') : `
      <div class="vacio card-lite"><span class="icono-vacio">${icono('calendar-days')}</span>
        <p>${activas ? 'No tienes citas activas.' : 'No hay citas canceladas.'}</p></div>`;
  }

  function fechaLarga(iso) {
    const d = new Date(`${iso}T00:00:00`);
    return isNaN(d) ? iso : d.toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short' });
  }

  function tarjetaCita(c) {
    const activa = c.estado === 'Confirmada';
    return `
      <article class="card cita">
        <div class="cita-cabecera">
          <div><strong>${esc(c.hospital)}</strong><p class="muted" style="font-size:14px">${esc(c.paciente)} · Ref. ${esc(c.id)}</p></div>
          <span class="estado ${activa ? 'ok' : 'cancelada'}">${activa ? 'Confirmada' : 'Cancelada'}</span>
        </div>
        <p class="cita-fecha">${icono('clock')}${esc(fechaLarga(c.fecha))} · ${esc(c.hora)}</p>
        ${c.motivo ? `<p class="muted" style="font-size:15px">${esc(c.motivo)}</p>` : ''}
        ${activa ? `<div class="btn-row">
          <button type="button" class="btn btn-outline btn-sm" data-accion="cambiar-cita" data-id="${esc(c.id)}">${icono('pencil')}Cambiar</button>
          <button type="button" class="btn btn-outline btn-sm" data-accion="cancelar-cita" data-id="${esc(c.id)}">${icono('x')}Cancelar</button>
        </div>` : ''}
      </article>`;
  }

  async function hojaCita() {
    const hs = await hospitalesParaCita();
    const r = estado.resultado;
    const preseleccion = r && r.hospitales.length ? r.hospitales[estado.seleccionado].id : (hs[0] && hs[0].id);
    const manana = new Date(Date.now() + 864e5);
    const motivo = r && r.modo === 'programada' && r.triaje.procedimiento ? r.triaje.procedimiento : '';
    abrirHoja(`
      <h2 id="sheet-titulo">Nueva cita</h2>
      <form class="form" id="f-cita" novalidate>
        <div class="campo"><label for="ci-hosp">Hospital</label>
          <select id="ci-hosp">${hs.map(h => `<option value="${esc(h.id)}"${h.id === preseleccion ? ' selected' : ''}>${esc(h.nombre)}</option>`).join('')}</select></div>
        <div class="campo"><label for="ci-nombre">Nombre del paciente</label><input id="ci-nombre" autocomplete="name" maxlength="120"></div>
        <div class="dos-col">
          <div class="campo"><label for="ci-fecha">Fecha</label><input id="ci-fecha" type="date" min="${fechaLocal(new Date())}" value="${fechaLocal(manana)}"></div>
          <div class="campo"><label for="ci-hora">Hora</label><input id="ci-hora" type="time" step="900" value="10:00"></div>
        </div>
        <div class="campo"><label for="ci-motivo">Motivo (opcional)</label><input id="ci-motivo" maxlength="300" value="${esc(motivo)}"></div>
        <button type="submit" class="btn btn-primary btn-block">${icono('check')}Confirmar cita</button>
      </form>
      <p class="nota">Simulación: no se envía a ningún hospital.</p>`,
    cuerpo => cuerpo.querySelector('#f-cita').addEventListener('submit', crearCita));
  }

  async function crearCita(e) {
    e.preventDefault();
    const datos = {
      hospital_id: $('#ci-hosp').value,
      paciente: $('#ci-nombre').value.trim(),
      fecha: $('#ci-fecha').value,
      hora: $('#ci-hora').value,
      motivo: $('#ci-motivo').value.trim(),
    };
    if (!datos.paciente) { toast('Escribe el nombre del paciente.'); $('#ci-nombre').focus(); return; }
    if (!datos.fecha || !datos.hora) { toast('Elige fecha y hora.'); return; }
    try {
      const c = await api('/api/citas', { method: 'POST', body: datos });
      cerrarHoja();
      toast(`Cita confirmada · Ref. ${c.id}`);
      estado.filtroCitas = 'activas';
      if (location.hash === '#citas') pintarCitas(); else location.hash = '#citas';
    } catch (err) {
      toast(err.message || 'No se ha podido crear la cita.');
    }
  }

  async function hojaCambioCita(id) {
    const citas = await api('/api/citas').catch(() => []);
    const c = citas.find(x => x.id === id);
    if (!c) return;
    abrirHoja(`
      <h2 id="sheet-titulo">Cambiar cita</h2>
      <p class="muted">${esc(c.hospital)}</p>
      <form class="form" id="f-cambio" novalidate>
        <div class="dos-col">
          <div class="campo"><label for="cc-fecha">Fecha</label><input id="cc-fecha" type="date" min="${fechaLocal(new Date())}" value="${esc(c.fecha)}"></div>
          <div class="campo"><label for="cc-hora">Hora</label><input id="cc-hora" type="time" step="900" value="${esc(c.hora)}"></div>
        </div>
        <button type="submit" class="btn btn-primary btn-block">${icono('check')}Guardar cambios</button>
      </form>`,
    cuerpo => cuerpo.querySelector('#f-cambio').addEventListener('submit', async e => {
      e.preventDefault();
      try {
        await api(`/api/citas/${encodeURIComponent(id)}`, { method: 'PATCH', body: { fecha: $('#cc-fecha').value, hora: $('#cc-hora').value } });
        cerrarHoja();
        toast('Cita cambiada');
        pintarCitas();
      } catch (err) {
        toast(err.message);
      }
    }));
  }

  async function cancelarCita(id, boton) {
    if (boton.dataset.confirmar !== '1') {
      boton.dataset.confirmar = '1';
      boton.classList.replace('btn-outline', 'btn-danger');
      boton.innerHTML = `${icono('x')}¿Seguro?`;
      setTimeout(() => {
        if (boton.isConnected && boton.dataset.confirmar === '1') {
          boton.dataset.confirmar = '';
          boton.classList.replace('btn-danger', 'btn-outline');
          boton.innerHTML = `${icono('x')}Cancelar`;
        }
      }, 3500);
      return;
    }
    try {
      await api(`/api/citas/${encodeURIComponent(id)}`, { method: 'DELETE' });
      toast('Cita cancelada');
      pintarCitas();
    } catch (err) {
      toast(err.message);
    }
  }

  // ------------------------------------------------------------------ mapa
  const COLOR_OCUPACION = { Baja: '#1E9E5A', Media: '#E3A008', Alta: '#D63A3A' };

  async function abrirMapa() {
    if (!window.L) { toast('No se ha podido cargar el mapa.'); return; }
    if (!estado.mapa) {
      estado.mapa = L.map('mapa', { zoomControl: false }).setView([40.42, -3.70], 11);
      L.control.zoom({ position: 'bottomright' }).addTo(estado.mapa);
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        subdomains: 'abcd',
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · © <a href="https://carto.com/attributions">CARTO</a>',
      }).addTo(estado.mapa);
      estado.capaHospitales = L.layerGroup().addTo(estado.mapa);
      estado.capaUsuario = L.layerGroup().addTo(estado.mapa);
      cargarParadasMapa();
    }
    setTimeout(() => estado.mapa.invalidateSize(), 60);
    await pintarHospitalesMapa();
  }

  async function pintarHospitalesMapa() {
    try {
      estado.hospitales = (await api('/api/hospitales')).hospitales;
    } catch {
      toast('No se han podido cargar los hospitales.');
      return;
    }
    estado.capaHospitales.clearLayers();
    const puntos = [];
    estado.hospitales.forEach(h => {
      L.circleMarker([h.lat, h.lon], {
        radius: 11, color: '#fff', weight: 3, fillColor: COLOR_OCUPACION[h.nivel_ocupacion] || '#5A6878', fillOpacity: 1,
      }).bindPopup(`
        <strong>${esc(h.nombre)}</strong><br>
        Espera ~${h.espera_min} min · Ocupación ${esc(String(h.nivel_ocupacion).toLowerCase())} (${pct(h.ocupacion_pct)} %)<br>
        Camas libres: ${h.camas_disponibles} de ${h.camas_urgencias}<br>
        <a class="popup-enlace" href="${rutaCoche(h)}" target="_blank" rel="noopener">Cómo llegar</a>`)
        .addTo(estado.capaHospitales);
      puntos.push([h.lat, h.lon]);
    });
    estado.capaUsuario.clearLayers();
    const u = estado.ubicacion;
    if (u) {
      L.circleMarker([u.lat, u.lon], { radius: 9, color: '#fff', weight: 3, fillColor: '#1F55C0', fillOpacity: 1 })
        .bindTooltip(u.origen === 'gps' ? 'Estás aquí' : esc(u.nombre))
        .addTo(estado.capaUsuario);
      puntos.push([u.lat, u.lon]);
    }
    if (!estado.mapaAjustado && puntos.length) {
      estado.mapa.fitBounds(puntos, { paddingTopLeft: [24, 76], paddingBottomRight: [24, 24] });
      estado.mapaAjustado = true;
    }
  }

  async function cargarParadasMapa() {
    try {
      const { paradas } = await api('/api/taxis/paradas');
      if (!paradas.length) return;
      const capa = L.layerGroup(paradas.map(p => L.circleMarker([p.lat, p.lon], {
        radius: 5, color: '#fff', weight: 1.5, fillColor: '#142233', fillOpacity: .9,
      }).bindPopup(`<strong>Parada de taxi</strong><br>${esc(p.nombre)}${p.plazas ? `<br>${p.plazas} plazas` : ''}${p.horario ? `<br>${esc(p.horario)}` : ''}`)));
      const btn = $('#btn-paradas');
      btn.hidden = false;
      btn.addEventListener('click', () => {
        const activo = btn.getAttribute('aria-pressed') !== 'true';
        btn.setAttribute('aria-pressed', String(activo));
        if (activo) capa.addTo(estado.mapa); else capa.remove();
      });
    } catch { /* sin paradas: no se muestra el botón */ }
  }

  // ------------------------------------------------------------------ eventos
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-accion]');
    if (!b) return;
    const accion = b.dataset.accion;
    const enHoja = Boolean(b.closest('.sheet'));
    switch (accion) {
      case 'volver': location.hash = '#inicio'; break;
      case 'taxi': hojaTaxi(); break;
      case 'avisar': hojaAvisar(); break;
      case 'elegir':
        estado.seleccionado = Number(b.dataset.i);
        pintarResultado();
        window.scrollTo(0, 0);
        break;
      case 'nueva-cita': hojaCita(); break;
      case 'nuevo-contacto': hojaContacto({}, enHoja ? hojaAvisar : null); break;
      case 'borrar-contacto': borrarContacto(Number(b.dataset.i), b); break;
      case 'copiar': copiar(b.dataset.texto); break;
      case 'cancelar-cita': cancelarCita(b.dataset.id, b); break;
      case 'cambiar-cita': hojaCambioCita(b.dataset.id); break;
      case 'filtro-citas': estado.filtroCitas = b.dataset.valor; pintarCitas(); break;
      default: break;
    }
  });

  function iniciar() {
    pintarIconos();
    $('#f-consulta').addEventListener('submit', buscar);
    $('#zona').addEventListener('change', elegirZona);
    $('#btn-gps').addEventListener('click', () => usarGPS(false));
    $$('.chip[data-texto]').forEach(chip => chip.addEventListener('click', () => { $('#mensaje').value = chip.dataset.texto; }));
    $('.sheet-fondo').addEventListener('click', cerrarHoja);
    $('.sheet-cerrar').addEventListener('click', cerrarHoja);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') cerrarHoja(); });
    window.addEventListener('hashchange', mostrar);
    cargarZonas();
    mostrar();
  }

  document.addEventListener('DOMContentLoaded', iniciar);
})();
