// 최근 작업 목록: 서버에 세션 목록 API가 없어 브라우저(localStorage)가 기억한다 (U9 2절).
// 읽기·쓰기는 모두 try/catch. 저장소를 못 쓰면 빈 목록으로 동작한다.
const KEY = 'lcim.recentSessions'
const MAX = 10

export const readRecent = () => {
  try {
    const list = JSON.parse(localStorage.getItem(KEY))
    return Array.isArray(list) ? list.filter((s) => s && typeof s.id === 'string') : []
  } catch {
    return []
  }
}

const write = (list) => {
  try {
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX)))
  } catch { /* 저장소를 못 쓰면 기억하지 않는다 */ }
}

// 같은 id 는 앞으로 옮기며 갱신한다
export const rememberSession = ({ id, filename, total }) =>
  write([{ id, filename, total, at: new Date().toISOString() }, ...readRecent().filter((s) => s.id !== id)])

export const forgetSession = (id) => write(readRecent().filter((s) => s.id !== id))
