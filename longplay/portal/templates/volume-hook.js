// Volume-control hook for the Kasm/Selkies desktop client.
(function () {
  'use strict';

  var pending = { volume: 0, muted: true }; // Start muted/silent to catch early boot audio
  var capturedGains = [];

  function targetGain() {
    return (pending.muted || pending.volume <= 0) ? 0 : pending.volume;
  }

  function applyVolume() {
    var gainVal = targetGain();
    for (var i = capturedGains.length - 1; i >= 0; i--) {
      var g = capturedGains[i];
      try {
        // Bypass overridden property setter using original AudioParam prototype
        if (AudioParam.prototype.setValueAtTime) {
          AudioParam.prototype.setValueAtTime.call(g.gain, gainVal, g.context.currentTime || 0);
        } else {
          g.gain.value = gainVal;
        }
      } catch (e) {
        capturedGains.splice(i, 1);
      }
    }

    // Fallback for direct HTML5 audio/video elements
    try {
      var els = document.querySelectorAll('video, audio');
      for (var j = 0; j < els.length; j++) {
        els[j].volume = pending.volume;
        els[j].muted = (pending.muted || pending.volume <= 0);
      }
    } catch (e) {}
  }

  function setVolume(v, m) {
    pending.volume = (typeof v === 'number' && isFinite(v)) ? Math.min(1, Math.max(0, v)) : 0;
    pending.muted = !!m;
    applyVolume();
  }

  // Lock an AudioParam so Selkies startup scripts cannot force it back to 1.0
  function clampGainParam(param, ctx) {
    try {
      // Intercept direct value assignment (e.g., gainNode.gain.value = 1.0)
      Object.defineProperty(param, 'value', {
        get: function () { return targetGain(); },
        set: function () {
          // Ignore Selkies' internal volume overrides; enforce targetGain()
          try {
            AudioParam.prototype.setValueAtTime.call(param, targetGain(), ctx.currentTime || 0);
          } catch (e) {}
        },
        configurable: true,
        enumerable: true
      });

      // Intercept scheduled assignments (e.g., gainNode.gain.setValueAtTime(1.0, ...))
      var origSetValueAtTime = param.setValueAtTime;
      param.setValueAtTime = function (val, time) {
        return origSetValueAtTime.call(this, targetGain(), time);
      };
    } catch (e) {}
  }

  function patchContextProto(Proto) {
    if (!Proto || typeof Proto.prototype.createGain !== 'function') return;
    var origCreateGain = Proto.prototype.createGain;

    Proto.prototype.createGain = function () {
      var gainNode = origCreateGain.apply(this, arguments);
      capturedGains.push(gainNode);

      // Lock down the gain parameter instantly
      clampGainParam(gainNode.gain, this);
      
      // Apply initial gain immediately
      try {
        AudioParam.prototype.setValueAtTime.call(gainNode.gain, targetGain(), this.currentTime || 0);
      } catch (e) {}

      return gainNode;
    };
  }

  if (window.AudioContext) patchContextProto(window.AudioContext);
  if (window.webkitAudioContext) patchContextProto(window.webkitAudioContext);

  // Control channels
  window.__lpSetVolume = setVolume;
  try {
    window.addEventListener('message', function (ev) {
      var d = ev.data;
      if (d && d.type === 'lp-set-volume') setVolume(d.volume, d.muted);
    });
  } catch (e) {}
})();