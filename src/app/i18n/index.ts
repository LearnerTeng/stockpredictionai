import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { en } from './locales/en'
import { ja } from './locales/ja'
import { zhCN } from './locales/zh-CN'

export const supportedLanguages = ['zh-CN', 'en', 'ja'] as const
export type AppLanguage = typeof supportedLanguages[number]
export const LANGUAGE_STORAGE_KEY = 'tradingai.language'

function initialLanguage(): AppLanguage {
  const saved = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
  return supportedLanguages.includes(saved as AppLanguage) ? saved as AppLanguage : 'zh-CN'
}

void i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': zhCN,
    en,
    ja,
  },
  lng: initialLanguage(),
  fallbackLng: 'en',
  defaultNS: 'common',
  ns: ['common', 'dashboard', 'portfolio', 'trading', 'assistant', 'charts', 'imageLab', 'stock', 'monitor', 'recommendations'],
  interpolation: { escapeValue: false },
  returnNull: false,
})

function persistLanguage(language: string) {
  const normalized = supportedLanguages.includes(language as AppLanguage) ? language as AppLanguage : 'en'
  window.localStorage.setItem(LANGUAGE_STORAGE_KEY, normalized)
  document.documentElement.lang = normalized
}

persistLanguage(i18n.resolvedLanguage ?? i18n.language)
i18n.on('languageChanged', persistLanguage)

export function currentLanguage(): AppLanguage {
  const language = i18n.resolvedLanguage ?? i18n.language
  return supportedLanguages.includes(language as AppLanguage) ? language as AppLanguage : 'en'
}

export default i18n
