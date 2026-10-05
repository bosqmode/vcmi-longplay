// Volume-control hook for the Kasm/Selkies desktop client.
//
// Design notes
// ------------
// * We drive only the Web Audio gain via the standard public API
//   (`GainNode.gain.setValueAtTime`). We do NOT override `AudioParam.value`,
//   `AudioParam.prototype.setValueAtTime`, or any other param method. Doing so
//   creates an unbounded recursion in Chromium (Edge/Chrome) that surfaces as:
//       RangeError: Maximum call stack size exceeded
//   because native setValueAtTime(round-trips through the `.value` property)
//   internally on that engine. Keeping the native implementations intact
//   sidesteps the bug on every engine.
//
// * We still patch `AudioContext.prototype.createGain`, but only to *record*
//   the gain nodes the client creates so we can reach the master later. That
//   patch is harmless on either browser because it installs no setter on any
//   engine-internal path.
//
// * To win the startup race (Selkies resets its master gain to 1.0 right
//   after the AudioContext starts running), we re-assert the target a few
//   times (50 ms apart for ~2 s) whenever a volume change is driven, AND
//   again whenever an AudioContext transitions into the "running" state.
//
// * A re-entrancy guard makes the apply path idempotent: if any engine
//   internal code ever re-enters us, we no-op rather than recurse.
//
// * Boot-seeding: at evaluation time we read the target straight from the
//   parent's localStorage (`lp_volume` / `lp_muted`). This works because the
//   desktop client is served SAME-ORIGIN via the /desktop/ reverse proxy, so it
//   shares localStorage with the portal page. Combined with an immediate
//   (non-scheduled) gain clamp and a tight ~50 ms boot re-assert burst, this
//   removes the ~100 ms full-volume burst on Chromium that happened before we
//   took over the client's audio graph. New users (no stored value) stay muted,
//   preserving the previous "silent until driven" behaviour.

(function () {
  'use strict';

  var pending = { volume: null, muted: true }; // silent until we learn the target
  var capturedGains = []; // every GainNode created via the (patched) AudioContext
  var reentrant = false;  // belt-and-suspenders guard

  // Learn the target from the portal's localStorage, which we share (desktop is
  // proxied same-origin under /desktop/). Runs at evaluation time so even our
  // very first clamp is already at the user's saved level rather than default.
  // New visitors have no stored value -> we stay muted (volume null) until the
  // parent drives us, exactly as before.
  function seedFromStorage() {
    try {
      var storedMuted = (window.localStorage.getItem('lp_muted') === 'true');
      if (storedMuted) {
        pending.muted = true;
        return;
      }
      var v = parseFloat(window.localStorage.getItem('lp_volume'));
      if (isFinite(v)) {
        pending.volume = Math.min(1, Math.max(0, v));
      }
    } catch (e) { /* not same-origin / storage unavailable – stay muted */ }
  }
  seedFromStorage();

  function gainValue() {
    if (pending.muted || pending.volume == null) return 0;
    return pending.volume <= 0 ? 0 : pending.volume;
  }

  function snapGain(node) {
    var ctx = node && node.context;
    var param = node && node.gain;
    if (!ctx || !param) return;
    var g = gainValue();
    // Set the value immediately (native setter) rather than through
    // setValueAtTime's automation scheduling. This removes any engine
    // scheduling delay, so the moment we touch a node it is already at the
    // target level — critical for closing Chromium's full-volume boot window.
    try { param.value = g; } catch (e) {
      if (typeof param.setValueAtTime === 'function') {
        try { param.setValueAtTime(g, ctx.currentTime || 0); } catch (e2) { /* ignore */ }
      }
    }
  }

  function applyToAll() {
    if (reentrant) return;
    reentrant = true;
    try {
      var i, node;
      for (i = 0; i < capturedGains.length; i++) {
        node = capturedGains[i];
        try { snapGain(node); } catch (e) { /* per-node failures are ignored */ }
      }
      // Fallback for direct HTML5 audio/video elements (some Kasm variants
      // carry audio there instead of through Web Audio).
      try {
        var els = document.querySelectorAll('video, audio');
        var tv = gainValue();
        for (i = 0; i < els.length; i++) {
          els[i].volume = tv;
          els[i].muted = (tv === 0);
        }
      } catch (e) { /* ignore */ }
    } finally {
      reentrant = false;
    }
  }

  // Bounded re-assert: win the startup race without freezing Selkies' param.
  // A tight 50 ms cadence for a couple of seconds is deliberately chosen so the
  // clamp lands inside Chromium's ~first-100 ms render window (the audible
  // burst) rather than after it; we still stop shortly after so we never pin
  // Selkies' live param once it is healthy.
  var reassertTimer = null;
  function startReassert() {
    if (reassertTimer) return;
    var ticks = 40; // 40 × 50ms ≈ 2 s
    reassertTimer = setInterval(function () {
      try { applyToAll(); } catch (e) { /* ignore */ }
      if (--ticks <= 0) {
        clearInterval(reassertTimer);
        reassertTimer = null;
      }
    }, 50);
  }

  function patchContext(Proto) {
    if (!Proto || typeof Proto.prototype.createGain !== 'function') return;
    var origCreateGain = Proto.prototype.createGain;

    Proto.prototype.createGain = function () {
      var node = origCreateGain.apply(this, arguments);

      // Record so we can reach the master gain later.
      try { capturedGains.push(node); } catch (e) { /* ignore */ }

      // Apply the pending target immediately: this silences early boot audio
      // before the parent's first volume drive and gives us a lead in the
      // race against Selkies' initial `gain.value = 1.0`.
      try { applyToAll(); } catch (e) { /* ignore */ }

      // When this AudioContext reaches "running" the client typically
      // finalizes its master gain; re-assert right after and arm a short
      // re-assert window to out-race any subsequent reset.
      try {
        if (this && typeof this.addEventListener === 'function' && !this._lpHookInstalled) {
          this._lpHookInstalled = true;
          this.addEventListener('statechange', function () {
            try { applyToAll(); startReassert(); } catch (e) { /* ignore */ }
          });
        }
      } catch (e) { /* ignore */ }

      return node;
    };
  }

  if (window.AudioContext) patchContext(window.AudioContext);
  if (window.webkitAudioContext) patchContext(window.webkitAudioContext);

  // ---- Control surface used by the parent portal -----------------------
  function setVolume(v, m) {
    pending.volume = (typeof v === 'number' && isFinite(v)) ? Math.min(1, Math.max(0, v)) : null;
    pending.muted = !!m;
    try { applyToAll(); } catch (e) { /* ignore */ }
    // Arm the bounded re-assert window so we out-race the client's reset.
    if (capturedGains.length > 0) startReassert();
  }

  window.__lpSetVolume = setVolume;

  try {
    window.addEventListener('message', function (ev) {
      var d = ev && ev.data;
      if (d && typeof d === 'object' && d.type === 'lp-set-volume') {
        setVolume(d.volume, d.muted);
      }
    });
  } catch (e) { /* ignore */ }
})();