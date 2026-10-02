// Volume-control hook for the Kasm/Selkies desktop client.
//
// Injected into the desktop's HTML (same-origin, via the /desktop/ reverse proxy) BEFORE the
// client boots. KasmVNC/Selkies play remote audio through the Web Audio API, so the standard
// <video>/<audio> volume properties do NOT reach it. This hook inserts a master GainNode into
// the Web Audio graph (between the client's output and the AudioContext destination) and lets
// the parent page drive it via:
//   - window.__lpSetVolume(volume, muted)   (direct same-origin call), or
//   - postMessage({ type: 'lp-set-volume', volume, muted }, '*')
(function () {
  'use strict';

  // Pending control state. Applied to any existing context immediately, and used as the
  // initial gain for any AudioContext created later (so an early "set" is never lost).
  var pending = { volume: 1, muted: false };
  function targetGain() { return (pending.muted || pending.volume <= 0) ? 0 : pending.volume; }

  var contexts = [];
  var realDests = new WeakMap();  // ctx -> original destination node (captured at creation)
  var gains = new WeakMap();      // ctx -> master GainNode, already wired to the real destination

  function ensureGain(ctx) {
    var g = gains.get(ctx);
    if (g) return g;
    g = ctx.createGain();
    g.gain.value = targetGain();
    var real = realDests.get(ctx) || ctx.destination;
    g.connect(real);
    gains.set(ctx, g);
    return g;
  }

  function applyToContext(ctx) {
    var g = gains.get(ctx);
    if (g) { try { g.gain.value = targetGain(); } catch (e) {} }
  }

  function applyAll() {
    for (var i = 0; i < contexts.length; i++) applyToContext(contexts[i]);
    // Fallback for clients that carry audio in a <video>/<audio> element instead of Web Audio.
    try {
      var els = document.querySelectorAll('video, audio');
      for (var j = 0; j < els.length; j++) {
        try { els[j].volume = pending.volume; els[j].muted = (pending.muted || pending.volume <= 0); } catch (e) {}
      }
    } catch (e) {}
  }

  function setVolume(v, m) {
    pending.volume = (typeof v === 'number' && isFinite(v)) ? Math.min(1, Math.max(0, v)) : 1;
    pending.muted = !!m;
    applyAll();
  }

  // Wrap AudioContext so we capture its real destination at creation time.
  function wrapAC(Orig) {
    return new Proxy(Orig, {
      construct: function (target, args) {
        var ctx = Reflect.construct(target, args);
        try { realDests.set(ctx, ctx.destination); contexts.push(ctx); } catch (e) {}
        return ctx;
      }
    });
  }
  if (typeof window.AudioContext === 'function') window.AudioContext = wrapAC(window.AudioContext);
  if (typeof window.webkitAudioContext === 'function') window.webkitAudioContext = wrapAC(window.webkitAudioContext);

  // Redirect the terminal connection (node -> destination) through the master gain:
  //   clientNode -> [masterGain] -> realDestination
  // This works regardless of whether the client caches ctx.destination or passes it directly.
  try {
    var AP = window.AudioNode && window.AudioNode.prototype;
    if (AP && typeof AP.connect === 'function') {
      var origConnect = AP.connect;
      AP.connect = function (dest, output, input) {
        try {
          var ctx = this && this.context;
          var real = ctx ? realDests.get(ctx) : null;
          if (ctx && real && dest === real) dest = ensureGain(ctx);
        } catch (e) {}
        return origConnect.call(this, dest, output, input);
      };
    }
  } catch (e) {}

  // Control channel: same-origin direct call + postMessage (safety net).
  window.__lpSetVolume = setVolume;
  try {
    window.addEventListener('message', function (ev) {
      var d = ev.data;
      if (d && d.type === 'lp-set-volume') setVolume(d.volume, d.muted);
    });
  } catch (e) {}
})();
