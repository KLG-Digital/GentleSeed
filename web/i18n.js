// ======================== TRADUCTIONS ========================
// L'anglais est la langue par défaut de tous les textes : rien à traduire. Les autres langues sont des fichiers
// web/locales/<langue>.json (clé = texte anglais). Un texte absent d'une langue reste en anglais.
'use strict';
window.GentleSeedI18n = (() => {
  const supported = ['fr', 'en', 'de', 'es', 'it', 'pt-PT', 'pt-BR', 'nl', 'pl', 'ru', 'ja', 'ko', 'zh-CN', 'uk'];
  let language = 'en';
  let dictionary = {};
  const originals = new WeakMap();

  // Langue à utiliser pour le choix « auto » (celle du navigateur) ou une langue demandée
  function locale(preferred) {
    const lang = preferred === 'auto' || !preferred ? navigator.language || 'en' : preferred;
    const normalized = lang.toLowerCase();
    if (normalized.startsWith('pt-br')) return 'pt-BR';
    if (normalized.startsWith('pt')) return 'pt-PT';
    if (normalized.startsWith('zh')) return 'zh-CN';
    return supported.find(value => value.toLowerCase() === normalized)
      || supported.find(value => value === normalized.split('-')[0])
      || 'en';
  }
  // =================================================


  // ======================== MODÈLES ET TRADUCTION D'UN TEXTE ========================
  // Une clé du dictionnaire peut contenir {} pour une valeur variable (« Insufficient seeders ({} < {}) »).
  // Dans la traduction, {} se remplit dans l'ordre ; {1} {2}… permettent de changer l'ordre selon la langue.
  let patterns = [];
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

  // Transforme chaque clé à {} en expression régulière (les plus longues d'abord)
  function compile() {
    patterns = Object.keys(dictionary)
      .filter(key => key.includes('{}'))
      .sort((a, b) => b.length - a.length)
      .map(key => {
        const source = key.split('{}').map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('(.+?)');
        return [new RegExp('^' + source + '$', 's'), dictionary[key] === key ? null : dictionary[key]];
      });
  }

  function fill(target, args) {
    let next = 0;
    return target.replace(/\{(\d*)\}/g, (whole, number) => {
      const value = args[number ? Number(number) - 1 : next++];
      return value === undefined ? whole : value;
    });
  }

  // Motif suivi de son nombre (« Insufficient seeders (0 < 1) (2) ») : chaque motif se traduit séparément
  const counted = /^(.*\S) \((\d{1,3})\)$/s;

  // Traduit un texte ; les valeurs variables sont elles aussi traduites (2 niveaux au plus)
  function t(value, depth = 0) {
    if (own(dictionary, value)) return dictionary[value];
    if (depth > 2) return value;
    const items = value.split('; ').map(item => counted.exec(item));
    if (items.every(Boolean)) return items.map(item => `${t(item[1], depth + 1)} (${item[2]})`).join('; ');
    for (const [pattern, target] of patterns) {
      const match = pattern.exec(value);
      if (match && target === null) return value;  // ligne technique : « /movie » ne devient pas « /film »
      if (match) return fill(target, match.slice(1).map(part => t(part, depth + 1)));
    }
    return value;
  }
  // =================================================


  // ======================== TRADUCTION DE LA PAGE ========================
  // Texte déjà traduit par nous : on garde l'original anglais pour pouvoir changer de langue
  const written = new WeakMap();
  const skipped = '#media, #tableColumnOptions, #fileRows';

  function translateText(text) {
    const element = text.parentElement;
    if (!element || ['SCRIPT', 'STYLE', 'PRE', 'CODE', 'TEXTAREA'].includes(element.tagName)) return;
    // translate="no" : donnée venue de l'extérieur (titre, release, indexeur, nom de fichier)
    if (element.closest(skipped) || element.closest('[translate="no"]')) return;
    let previous;
    if (written.has(text) && text.nodeValue === written.get(text)) {
      previous = originals.get(text);
    } else {
      previous = text.nodeValue;
      originals.set(text, previous);
    }
    // Les espaces autour du texte sont conservés, seul le texte du milieu est traduit
    const match = previous.match(/^(\s*)(.*?)(\s*)$/s);
    if (!match) return;
    // Un paragraphe écrit sur plusieurs lignes dans le HTML correspond à une clé d'une seule ligne
    const flat = match[2].replace(/\s+/g, ' ');
    const translated = t(flat);
    const next = translated === flat ? previous : match[1] + translated + match[3];
    if (next !== text.nodeValue) text.nodeValue = next;
    written.set(text, next);
  }

  // Nœud de texte créé par l'interface, déjà traduit : il retient l'anglais pour suivre un changement de langue
  function textNode(value) {
    const source = String(value);
    const node = document.createTextNode(t(source));
    originals.set(node, source);
    written.set(node, node.nodeValue);
    return node;
  }

  // Attributs lus par l'utilisateur (infobulles, champs, lecteurs d'écran)
  const attributes = ['title', 'placeholder', 'aria-label', 'alt'];
  const attributeOriginals = new WeakMap();
  const attributeWritten = new WeakMap();

  function translateAttribute(element, name) {
    if (!element.hasAttribute(name) || element.closest(skipped)) return;
    const originals = attributeOriginals.get(element) || {};
    const written = attributeWritten.get(element) || {};
    const current = element.getAttribute(name);
    const previous = (name in written && current === written[name]) ? originals[name] : current;
    originals[name] = previous;
    const next = t(previous);
    if (next !== current) element.setAttribute(name, next);
    written[name] = next;
    attributeOriginals.set(element, originals);
    attributeWritten.set(element, written);
  }

  function translateElement(element) {
    for (const name of attributes) translateAttribute(element, name);
  }

  function translateTree(root) {
    if (root.nodeType === Node.TEXT_NODE) {
      translateText(root);
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    translateElement(root);
    root.querySelectorAll('[title],[placeholder],[aria-label],[alt]').forEach(translateElement);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let text;
    while ((text = walker.nextNode())) translateText(text);
  }

  function translateStatic() {
    translateTree(document.body);
    if (!originals.has(document)) originals.set(document, document.title);
    document.title = t(originals.get(document));
    document.documentElement.lang = language;
  }
  // =================================================


  // ======================== SUIVI DES CHANGEMENTS ET CHARGEMENT ========================
  // Les textes ajoutés ensuite par l'interface (messages, journaux, résultats) sont traduits au passage
  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') translateText(record.target);
      else if (record.type === 'attributes') translateAttribute(record.target, record.attributeName);
      else record.addedNodes.forEach(translateTree);
    }
  });

  function watch(on) {
    observer.disconnect();
    if (on) observer.observe(document.body, {childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: attributes});
  }

  async function load(name) {
    const response = await fetch('static/locales/' + encodeURIComponent(name) + '.json', {cache: 'no-cache'});
    if (!response.ok) throw Error('Translation file not found');
    return response.json();
  }

  // Applique une langue ; une demande plus récente annule la précédente
  let request = 0;
  async function apply(preferred) {
    const next = locale(preferred);
    const id = ++request;
    if (next === 'en') {
      language = 'en';
      dictionary = {};
      patterns = [];
      watch(false);
      translateStatic();
      return;
    }
    try {
      const data = await load(next);
      if (request !== id) return;
      dictionary = data;
      language = next;
      compile();
      translateStatic();
      watch(true);
    } catch (error) {
      console.warn('GentleSeed i18n', error);
      if (request !== id) return;
      dictionary = {};
      patterns = [];
      language = 'en';
      watch(false);
      translateStatic();
    }
  }

  // Pages sans session (connexion, accès refusé) : langue réglée sur le serveur ; à défaut, celle du navigateur
  async function applyServer() {
    let preferred = localStorage.getItem('gentleseed.locale') || 'auto';
    try {
      const response = await fetch('api/language', {credentials: 'same-origin', cache: 'no-store'});
      if (response.ok) preferred = (await response.json()).language || 'auto';
    } catch (_) {}
    return apply(preferred);
  }

  return {locale, t, textNode, apply, applyServer, get language() { return language; }, supported};
})();
// =================================================
