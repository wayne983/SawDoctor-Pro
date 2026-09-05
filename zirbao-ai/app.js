(function (global) {
  'use strict';

  const SITE_HOSTNAME = 'www.hawer-knife.com';
  const LINE_DOCTOR_URL = 'https://line.me/ti/p/%40drhawer';
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
        lineUrl: LINE_DOCTOR_URL
      };
    }

    if (DANGER_KEYWORDS.some((keyword) => normalizedQuery.includes(keyword))) {
      return {
        mode: 'danger',
        message: '出現可能影響安全的異常時，請先停機檢查。此處僅能提供初步導引，請交由鋸片醫生真人技師確認。',
        questions: ['請先停止機台運轉。', '請保留鋸片與異常位置照片供技師確認。'],
        cards: [],
        lineUrl: LINE_DOCTOR_URL
      };
    }

    const cards = matchingCards(normalizedQuery);
    const hasMachine = /機台|切斷機|圓鋸機|鋸床/.test(normalizedQuery);

    return {
      mode: 'guide',
      message: cards.length
        ? '我先為您找到以下相關產品或服務。實際選用仍須依材料、機台與現場條件確認。'
        : '我還需要多一點資料，才能幫您縮小方向。您也可以交給真人技師確認。',
      questions: hasMachine
        ? ['請補充工件外徑、厚度或實際切割用途。']
        : ['請補充使用的機台、工件尺寸／厚度與切割用途。'],
      cards,
      lineUrl: LINE_DOCTOR_URL
    };
  }

  const ZirbaoGuide = {
    LINE_DOCTOR_URL,
    normalizeText,
    isTrustedHawerUrl,
    answer
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ZirbaoGuide };
  }

  global.ZirbaoGuide = ZirbaoGuide;
})(typeof window !== 'undefined' ? window : globalThis);
