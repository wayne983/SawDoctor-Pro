(function (global) {
  'use strict';

  const SITE_HOSTNAME = 'www.hawer-knife.com';
  const LINE_DOCTOR_URL = 'https://line.me/ti/p/%40drhawer';
  const DIAGNOSIS_URL = 'https://www.hawer-knife.com/Product_sCats.asp?productscatid=833957866333';
  const DANGER_KEYWORDS = ['裂紋', '裂痕', '缺齒', '掉齒', '變形', '劇烈震動', '異常震動', '冒煙', '火花'];

  const PAGE_INDEX = [
    {
      title: '鋁棒、鋁胚與鋁錠用大外徑鋸片',
      summary: '適用鋁棒、鋁胚、鋁錠與鋁擠型的大外徑圓鋸片。',
      url: 'https://www.hawer-knife.com/ProductDetails.asp?produid=187',
      keywords: ['鋁棒', '鋁胚', '鋁錠', '鋁擠型', '大外徑']
    },
    {
      title: '鋁合金用圓鋸片',
      summary: '查看鋁管、鋁板、鋁棒與銅件的圓鋸片產品。',
      url: 'https://www.hawer-knife.com/ProductDetails.asp?produid=19',
      keywords: ['鋁管', '鋁板', '鋁合金', '銅件', '355', '610']
    },
    {
      title: '型鋼冷切與熱切鋸片',
      summary: '查看型鋼、鋼鐵冷切與熱切的大外徑鋸片。',
      url: 'https://www.hawer-knife.com/ProductDetails.asp?produid=192',
      keywords: ['型鋼', '鋼鐵', '冷切', '熱切']
    },
    {
      title: '鋸片研磨與維修',
      summary: '了解鋸片研磨、修磨、顯微檢查與售後維修服務。',
      url: 'https://www.hawer-knife.com/Product_sCats.asp?productscatid=288508731574',
      keywords: ['研磨', '修磨', '維修', '鈍齒', '齒面']
    },
    {
      title: '鋸片診療系統',
      summary: '由真人技師進行鋸片健檢與後續確認。',
      url: 'https://www.hawer-knife.com/Product_sCats.asp?productscatid=833957866333',
      keywords: ['診療', '健檢', '異常', '切面毛邊', '毛邊']
    },
    {
      title: '木工與塑料用鋸片',
      summary: '查看木材、壓克力與塑料加工用圓鋸片。',
      url: 'https://www.hawer-knife.com/ProductDetails.asp?produid=1',
      keywords: ['木工', '木材', '壓克力', '塑料', '塑膠']
    }
  ];

  function normalizeText(value) {
    if (typeof value !== 'string') return '';
    return value.normalize('NFKC')
      .replace(/[，,。．、；;：:！？!?／/\\|()（）［］【】「」『』<>《》]+/g, ' ')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, ' ');
  }

  function isTrustedHawerUrl(value) {
    try {
      const url = new URL(String(value));
      return url.protocol === 'https:' && url.hostname.toLowerCase() === SITE_HOSTNAME;
    } catch (error) {
      return false;
    }
  }

  function matchingCards(normalizedQuery) {
    return PAGE_INDEX
      .filter((page) => isTrustedHawerUrl(page.url))
      .map((page, index) => ({
        page,
        index,
        score: page.keywords.filter((keyword) => normalizedQuery.includes(normalizeText(keyword))).length
      }))
      .filter((item) => item.score > 0)
      .sort((left, right) => right.score - left.score || left.index - right.index)
      .slice(0, 3)
      .map((item) => item.page);
  }

  function answer(query) {
    const normalizedQuery = normalizeText(query);

    if (!normalizedQuery) {
      return {
        mode: 'empty',
        message: '嗨！我是鋸寶。告訴我您要切什麼材料，或遇到什麼狀況，我會先幫您找方向。',
        questions: ['材料是什麼？', '工件尺寸或厚度是多少？', '使用什麼機台？'],
        cards: [],
        lineUrl: LINE_DOCTOR_URL,
        needsDiagnosis: false,
        diagnosisUrl: ''
      };
    }

    if (DANGER_KEYWORDS.some((keyword) => normalizedQuery.includes(keyword))) {
      return {
        mode: 'danger',
        message: '出現可能影響安全的異常時，請先停機檢查。此處僅能提供初步導引，請交由鋸片醫生真人技師確認。',
        questions: ['請先停止機台運轉。', '請保留鋸片與異常位置照片供技師確認。'],
        cards: [],
        lineUrl: LINE_DOCTOR_URL,
        needsDiagnosis: false,
        diagnosisUrl: ''
      };
    }

    const cards = matchingCards(normalizedQuery);
    const diagnosisNeeded = needsDiagnosis(normalizedQuery);
    if (/不鏽鋼/.test(normalizedQuery) && /方管|管/.test(normalizedQuery) && hasDimensions(normalizedQuery) && diagnosisNeeded) {
      return {
        mode: 'guide',
        message: '您已提供不鏽鋼方管與截面尺寸。可先由鋸片醫生評估高速鋼鋸片或 14 吋鐵工鋸片的方向；實際是否適用仍取決於機台型式、可裝尺寸與主軸轉速，不能直接指定規格。',
        questions: missingConditionQuestions(normalizedQuery),
        cards: [],
        lineUrl: LINE_DOCTOR_URL,
        needsDiagnosis: true,
        diagnosisUrl: DIAGNOSIS_URL
      };
    }

    return {
      mode: 'guide',
      message: cards.length
        ? '我先為您找到以下相關產品或服務。實際選用仍須依材料、機台與現場條件確認。'
        : '我還需要多一點資料，才能幫您縮小方向。',
      questions: missingConditionQuestions(normalizedQuery),
      cards,
      lineUrl: LINE_DOCTOR_URL,
      needsDiagnosis: diagnosisNeeded,
      diagnosisUrl: diagnosisNeeded ? DIAGNOSIS_URL : ''
    };
  }

  const ZirbaoGuide = {
    LINE_DOCTOR_URL,
    DIAGNOSIS_URL,
    normalizeText,
    isTrustedHawerUrl,
    answer
  };

  function createElement(documentRef, tag, className, text) {
    const item = documentRef.createElement(tag);
    if (className) item.className = className;
    if (text) item.textContent = text;
    return item;
  }

  function hasMaterial(query) { return /不鏽鋼|鋼|鐵|鋁|銅|木材|木工|塑膠|塑料|壓克力/.test(query); }
  function hasDimensions(query) { return /\d+(?:\.\d+)?\s*(?:x|\*)\s*\d+(?:\.\d+)?(?:\s*(?:x|\*)\s*\d+(?:\.\d+)?)?\s*(?:mm|毫米)?/.test(query); }
  function hasMachine(query) { return /機台|切斷機|圓鋸機|鋸床|冷鋸|乾切|鐵工/.test(query); }
  function hasRpm(query) { return /\d{2,5}\s*(?:rpm|轉\/分|轉每分|轉)/.test(query); }
  function needsDiagnosis(query) { return !(hasMaterial(query) && hasDimensions(query) && hasMachine(query) && hasRpm(query)); }
  function missingConditionQuestions(query) {
    const questions = [];
    if (!hasMachine(query)) questions.push('請提供使用的機台型式，例如冷鋸機、乾切機、圓鋸機或切斷機。');
    if (!hasRpm(query)) questions.push('請提供機台主軸轉速約多少 RPM。');
    if (!hasMaterial(query) || !hasDimensions(query)) questions.push('請補充材料與工件尺寸／厚度。');
    return questions.slice(0, 3);
  }

  function createConversation(client, fallback) {
    const turns = [];

    async function ask(question) {
      const text = String(question || '').trim();
      turns.push({ role: 'user', text });
      const reply = client ? await client.sendQuestion(text) : fallback(text);
      turns.push({ role: 'assistant', reply });
      return reply;
    }

    return Object.freeze({
      ask,
      turns: () => turns.slice()
    });
  }

  function initializeZirbaoApp(documentRef) {
    const input = documentRef.getElementById('zirbao-query');
    const send = documentRef.getElementById('zirbao-send');
    const results = documentRef.getElementById('zirbao-results');
    const lineLink = documentRef.getElementById('zirbao-line');

    if (!input || !send || !results || !lineLink) return;
    const client = global.ZirbaoClient
      ? global.ZirbaoClient.createClient(
        global.ZIRBAO_AI_CONFIG || { endpoint: '' },
        answer,
        global.ZirbaoClient.createIframeTransport(documentRef, global)
      )
      : null;

    function scrollToLatest() {
      results.scrollTop = results.scrollHeight;
    }

    function createTurn(role) {
      return createElement(documentRef, 'article', `zirbao-turn zirbao-turn-${role}`);
    }

    function renderUser(question) {
      const turn = createTurn('user');
      turn.append(createElement(documentRef, 'div', 'zirbao-message', question));
      results.append(turn);
      scrollToLatest();
    }

    function renderLoading() {
      const turn = createTurn('assistant');
      turn.append(createElement(documentRef, 'div', 'zirbao-message zirbao-message-loading', '鋸寶正在整理資料…'));
      results.append(turn);
      scrollToLatest();
      return turn;
    }

    function renderReply(reply) {
      const turn = createTurn('assistant');

      const message = createElement(documentRef, 'div', 'zirbao-message', reply.message);
      if (reply.mode === 'danger') message.classList.add('zirbao-message-danger');
      turn.append(message);

      const followUps = reply.followUpQuestions || reply.questions || [];
      if (followUps.length) {
        const questions = createElement(documentRef, 'div', 'zirbao-questions');
        questions.textContent = followUps.join('　');
        turn.append(questions);
      }

      if (reply.cards.length) {
        const cards = createElement(documentRef, 'div', 'zirbao-cards');
        reply.cards.forEach((card) => {
          const link = createElement(documentRef, 'a', 'zirbao-card');
          const title = createElement(documentRef, 'strong', '', card.title);
          const summary = createElement(documentRef, 'span', '', card.summary);
          link.href = card.url;
          link.target = '_blank';
          link.rel = 'noopener';
          link.append(title, summary);
          cards.append(link);
        });
        turn.append(cards);
      }

      if (reply.needsDiagnosis && isTrustedHawerUrl(reply.diagnosisUrl)) {
        const diagnosisLink = createElement(documentRef, 'a', 'zirbao-diagnosis-link', '填寫鋸片診療資料');
        diagnosisLink.href = reply.diagnosisUrl;
        diagnosisLink.target = '_blank';
        diagnosisLink.rel = 'noopener';
        turn.append(diagnosisLink);
      }

      results.append(turn);
      lineLink.href = reply.lineUrl;
      scrollToLatest();
    }

    const conversation = createConversation(client, answer);

    async function submitQuery(query) {
      const question = String(query || '').trim();
      if (!question) {
        input.focus();
        return;
      }
      renderUser(question);
      input.value = '';
      const loading = renderLoading();
      send.disabled = true;
      try {
        const reply = await conversation.ask(question);
        loading.remove();
        renderReply(reply);
      } finally {
        if (loading.isConnected) loading.remove();
        send.disabled = false;
        input.focus();
      }
    }

    send.addEventListener('click', () => submitQuery(input.value));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        submitQuery(input.value);
      }
    });

    documentRef.querySelectorAll('[data-zirbao-shortcut]').forEach((button) => {
      button.addEventListener('click', () => {
        const query = button.getAttribute('data-zirbao-shortcut') || '';
        input.value = query;
        submitQuery(query);
      });
    });
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ZirbaoGuide, ZirbaoChat: { createConversation } };
  }

  global.ZirbaoGuide = ZirbaoGuide;
  global.ZirbaoChat = { createConversation };
  global.initializeZirbaoApp = initializeZirbaoApp;

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => initializeZirbaoApp(document), { once: true });
    } else {
      initializeZirbaoApp(document);
    }
  }
})(typeof window !== 'undefined' ? window : globalThis);
