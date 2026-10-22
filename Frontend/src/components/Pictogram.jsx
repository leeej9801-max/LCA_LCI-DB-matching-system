// 소개 화면 픽토그램: 인라인 SVG 선 아이콘(굵기 약 2px, currentColor). 장식이라 스크린리더에서 숨긴다. 외부 이미지·아이콘 라이브러리 없음
const PATHS = {
  name: <><path d="M4 7h8l4 5-4 5H4z" /><path d="M18 7l3 5-3 5" /></>, // 같은 부품, 다른 이름(태그 두 개)
  layers: <><path d="M12 4l8 4-8 4-8-4z" /><path d="M4 12l8 4 8-4" /><path d="M4 16l8 4 8-4" /></>, // 소재와 공정이 겹침
  ruler: <><rect x="3" y="8" width="18" height="8" rx="1.5" /><path d="M7 8v3M11 8v4M15 8v3M19 8v4" /></>, // 단위
  search: <><circle cx="11" cy="11" r="6" /><path d="M20 20l-4.5-4.5" /></>,
  shield: <><path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z" /><path d="M8.5 12l2.5 2.5L15.5 10" /></>, // 승인·걸러냄
  doc: <><path d="M6 3h9l4 4v14H6z" /><path d="M14 3v5h5M9 13h7M9 17h5" /></>,
  scale: <path d="M12 4v16M6 20h12M4 8h16M4 8l-2 6a3 3 0 0 0 6 0zM20 8l-2 6a3 3 0 0 0 6 0z" />, // 저울(단위 변환)
  network: <><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="6" r="2.5" /><circle cx="12" cy="18" r="2.5" /><path d="M8 7.5l3 8M16 7.5l-3 8M8.5 6h7" /></>, // 의미 유사
  upload: <><path d="M12 16V5M7 10l5-5 5 5" /><path d="M5 19h14" /></>,
}

const Pictogram = ({ name, size = 24, strokeWidth = 2 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    {PATHS[name]}
  </svg>
)

export default Pictogram
