(function (global) {
  'use strict';

  var HAWER_HOSTNAME = 'www.hawer-knife.com';
  var LINE_DOCTOR_URL = 'https://line.me/ti/p/%40drhawer';

  function isTrustedHawerUrl(value) {
    try {
      var url = new URL(String(value));
      return url.protocol === 'https:' && url.hostname.toLowerCase() === HAWER_HOSTNAME;
    } catch (error) {
      return false;
    }
  }

  function isTrustedAppsScriptOrigin(value) {
    try {
      var url = new URL(String(value));
      var hostname = url.hostname.toLowerCase();
      return url.protocol === 'https:' && (
        hostname === 'script.google.com' ||
        hostname === 'script.googleusercontent.com' ||
        /(^|[-.])script\.googleusercontent\.com$/.test(hostname)
      );
    } catch (error) {
      return false;
    }
  }

  function requestId() {
    return 'zirbao_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
  }

  function sanitizeReply(reply) {
    var source = reply && typeof reply === 'object' ? reply : {};
    return {
      mode: typeof source.mode === 'string' ? source.mode : 'answer',
      message: typeof source.message === 'string' ? source.message.slice(0, 1800) : '我先幫您整理目前可確認的方向。',
      followUpQuestions: Array.isArray(source.followUpQuestions) ? source.followUpQuestions.filter(function (item) { return typeof item === 'string' && item.trim(); }).slice(0, 3) : [],
      cards: Array.isArray(source.cards) ? source.cards.filter(function (card) {
        return card && typeof card.title === 'string' && typeof card.summary === 'string' && isTrustedHawerUrl(card.url);
      }).slice(0, 3) : [],
      lineUrl: LINE_DOCTOR_URL
    };
  }

  function createClient(config, fallback, transport, dangerCheck, safetyReply) {
    var endpoint = config && typeof config.endpoint === 'string' ? config.endpoint.trim() : '';
    var history = [];
    var isDangerous = dangerCheck || function (question) { return !!(global.ZirbaoCore && global.ZirbaoCore.isDangerous(question)); };
    var buildSafetyReply = safetyReply || function () { return global.ZirbaoCore.createSafetyReply(); };

    function addHistory(role, text) {
      history.push({ role: role, text: String(text).slice(0, 1000) });
      if (history.length > 6) history.splice(0, history.length - 6);
    }

    async function sendQuestion(question) {
      var input = String(question || '').trim();
      if (isDangerous(input)) {
        var safety = sanitizeReply(buildSafetyReply(input));
        addHistory('user', input);
        addHistory('assistant', safety.message);
        return Object.assign({ source: 'local-safety' }, safety);
      }
      if (!endpoint || typeof transport !== 'function') {
        var local = sanitizeReply(fallback(input));
        addHistory('user', input);
        addHistory('assistant', local.message);
        return Object.assign({ source: 'local-fallback' }, local);
      }
      var payload = { requestId: requestId(), question: input, history: history.slice(-6) };
      try {
        var response = await transport(payload, endpoint);
        if (!response || response.type !== 'zirbao-ai-reply' || response.requestId !== payload.requestId || response.ok !== true || !response.reply) throw new Error('後端回覆格式錯誤');
        var aiReply = sanitizeReply(response.reply);
        addHistory('user', input);
        addHistory('assistant', aiReply.message);
        return Object.assign({ source: 'ai' }, aiReply);
      } catch (error) {
        var recovered = sanitizeReply(fallback(input));
        recovered.message = '目前無法取得 AI 回覆。' + recovered.message;
        addHistory('user', input);
        addHistory('assistant', recovered.message);
        return Object.assign({ source: 'local-fallback', unavailable: true }, recovered);
      }
    }

    return Object.freeze({ sendQuestion: sendQuestion, history: function () { return history.slice(); } });
  }

  function createIframeTransport(documentRef, windowRef) {
    var pending = {};
    windowRef.addEventListener('message', function (event) {
      if (!isTrustedAppsScriptOrigin(event.origin) || !event.data || event.data.type !== 'zirbao-ai-reply') return;
      var request = pending[event.data.requestId];
      if (!request) return;
      windowRef.clearTimeout(request.timer);
      delete pending[event.data.requestId];
      request.resolve(event.data);
    });
    return function (payload, endpoint) {
      return new Promise(function (resolve, reject) {
        var frame = documentRef.getElementById('zirbao-ai-frame');
        if (!frame) { reject(new Error('找不到 AI 回覆框架')); return; }
        var form = documentRef.createElement('form');
        var field = documentRef.createElement('input');
        field.name = 'payload';
        field.value = JSON.stringify(payload);
        form.method = 'post';
        form.action = endpoint;
        form.target = frame.name;
        form.style.display = 'none';
        form.append(field);
        documentRef.body.append(form);
        pending[payload.requestId] = {
          resolve: resolve,
          timer: windowRef.setTimeout(function () {
            delete pending[payload.requestId];
            form.remove();
            reject(new Error('AI 回覆逾時'));
          }, 20000)
        };
        form.submit();
        form.remove();
      });
    };
  }

  var api = Object.freeze({ createClient: createClient, createIframeTransport: createIframeTransport, sanitizeReply: sanitizeReply, isTrustedHawerUrl: isTrustedHawerUrl });
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.ZirbaoClient = api;
})(typeof window !== 'undefined' ? window : globalThis);
