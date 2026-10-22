// 운영(real) 빌드에서만 관리 메뉴·경로를 숨긴다. .env.real 의 VITE_HIDE_ADMIN=1 + 빌드(PROD)일 때만이라 npm run dev / dev:real 은 그대로다
export const HIDE_ADMIN = import.meta.env.PROD && import.meta.env.VITE_HIDE_ADMIN === '1'
