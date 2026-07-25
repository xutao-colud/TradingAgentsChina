# 小团队登录页交互重构

## 目标

修复测试登录接口的路由兼容问题，并把登录页改造成与 A 股证据研究场景一致的交互入口。

## 交互

- 人物眼球跟随鼠标，但移动距离有上限。
- 聚焦账号或密码输入框时，人物统一看向右侧表单。
- 显示密码时，前排人物遮眼，后排人物转移视线。
- 人物随机眨眼并有轻微呼吸动画；系统开启“减少动态效果”时禁用非必要动画。
- 登录失败保留用户输入，只展示可执行的中文错误。

## 布局

左侧采用品牌、人物舞台、产品说明、原则栏四个独立区域。人物舞台不承载大标题，避免文案覆盖人物。右侧登录表单保持固定可读宽度，并针对窄屏降为单列。

## 路由与缓存

- API 路径统一移除尾斜杠并忽略查询参数。
- 登录相关接口保留公开访问。
- HTML、CSS、JavaScript 使用 `no-store`，避免长驻 Python 进程读取新静态文件后出现前后端版本错配。
- 404 且返回 `Unknown API route` 时，前端提示用户重启后端服务。

## 验证

- 登录接口支持 `/api/session/login` 和 `/api/session/login/`。
- 登录、退出、会话隔离测试通过。
- 桌面与移动端无文字覆盖、无横向滚动。
- 鼠标、输入框焦点、密码显示和眨眼状态均在真实浏览器中验证。
# 2026-07-25 interaction correction

The character stage follows pointer movement across the entire viewport,
including the form panel. Whole faces move with the pointer while bodies use
small bottom-anchored skew and translation. Motion is interpolated through
`requestAnimationFrame`; tall bars never rotate around their base.

Password entry uses a persistent privacy posture. As soon as the password field
receives focus, every character rotates its full body 180 degrees and stops
following the pointer. The back layer uses a V-shaped shoulder yoke and a
vertical seam, rather than a single curve that could be mistaken for closed
eyes. The characters remain back-facing after blur for as long as a concealed
password exists. When the user reveals the password, the characters face
forward again but close every eye. Closed-eye dimensions are applied without
transition before the face fades in, preventing an open-eye flash. The toggle
explicitly
says `显示` or `隐藏`, and page initialization always restores the secure
password type.

Returning from the authenticated application explicitly resumes the character
stage. Hiding the login view cancels pending animation and blink timers; showing
it removes stale blink classes and starts a fresh animation frame. This prevents
background-tab throttling from leaving white eyes or a permanently suspended
motion loop. Desktop characters use narrower widths and lower height ratios so
the sculpture, price line, evidence chips, and editorial copy retain distinct
visual space.

Acceptance checks:

- moving the pointer from the far left to the password toggle changes every
  character body's computed `translate` and `skew` without large rotation;
- password input stays masked until the user explicitly chooses `显示`;
- focusing or retaining a concealed password keeps every body at 180 degrees,
  with no pointer-following response;
- revealing the password produces a direct closed-eye pose with no open-eye
  intermediate frame;
- the behavior remains usable at desktop and mobile widths and honors reduced
  motion settings.
