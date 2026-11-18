import { currentLanguage } from './index'
import type { MarketCode } from '../types'

export type CurrencyCode = 'USD' | 'JPY' | 'HKD'

export const currencyForMarket = (market?: MarketCode): CurrencyCode => (
  market === 'JP' ? 'JPY' : market === 'HK' ? 'HKD' : 'USD'
)

export function formatMoney(value: number, currency: CurrencyCode = 'USD', maximumFractionDigits = 0) {
  return new Intl.NumberFormat(currentLanguage(), {
    style: 'currency',
    currency,
    maximumFractionDigits,
  }).format(value)
}

export function formatNumber(value: number, digits = 2) {
  return new Intl.NumberFormat(currentLanguage(), {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value)
}

export function formatDateTime(value: string | number | Date) {
  return new Intl.DateTimeFormat(currentLanguage(), {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}
