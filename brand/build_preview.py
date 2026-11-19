"""把 brand/ 下的 SVG 组装成一页可滚动的标识展示页。"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent


def load(name: str) -> str:
    return (OUT / name).read_text(encoding="utf-8")


def inline(name: str, w: str, cls: str = "") -> str:
    svg = load(name)
    svg = svg.replace('width="1024" height="1024"', f'width="{w}" height="{w}"')
    svg = svg.replace("<svg ", f'<svg class="{cls}" ', 1)
    return svg


HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Ocelot · 标识方案</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: #F7F7F8; color: #111114;
    font-family: -apple-system, "SF Pro Text", "Helvetica Neue", "PingFang SC", sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 56px 40px 80px; }}
  header {{ display: flex; align-items: flex-end; gap: 28px; margin-bottom: 44px; }}
  header .big {{ width: 150px; }}
  header h1 {{ font-size: 26px; font-weight: 600; margin: 0 0 6px; letter-spacing: .01em; }}
  header p {{ margin: 0; font-size: 13.5px; color: #7C7C82; line-height: 1.6; }}
  section {{ margin-bottom: 40px; }}
  .label {{
    font-size: 11px; letter-spacing: .18em; text-transform: uppercase;
    color: #9A9AA0; margin-bottom: 14px; font-weight: 500;
  }}
  .card {{
    background: #fff; border: 1px solid #E8E8EA; border-radius: 18px;
    padding: 34px; display: flex; align-items: center; gap: 44px; flex-wrap: wrap;
  }}
  .card.dark {{ background: #0B0B0C; border-color: #1B1B1E; }}
  .mk {{ width: 128px; height: 128px; flex: 0 0 auto; }}
  .lk {{ height: 74px; width: auto; }}
  .wm {{ height: 46px; width: auto; }}
  .icn {{ width: 104px; height: 104px; border-radius: 0; }}
  .scale {{ display: flex; align-items: flex-end; gap: 30px; background: #fff;
            border: 1px solid #E8E8EA; border-radius: 18px; padding: 30px 34px; }}
  .scale div {{ text-align: center; color: #A0A0A6; font-size: 10.5px; }}
  .scale svg {{ display: block; margin: 0 auto 10px; }}
  .notes {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }}
  .note {{ background: #fff; border: 1px solid #E8E8EA; border-radius: 14px; padding: 18px 20px; }}
  .note b {{ display: block; font-size: 12.5px; font-weight: 600; margin-bottom: 6px; }}
  .note span {{ font-size: 12.2px; color: #7C7C82; line-height: 1.65; }}
  .files {{ font-size: 12px; color: #7C7C82; line-height: 2; font-family: "SF Mono", Menlo, monospace; }}
</style>
</head>
<body>
<div class="wrap">

  <header>
    {mark_big}
    <div>
      <h1>Ocelot 标识</h1>
      <p>单一线宽的线条标：5/96 的等粗描边、纯几何构成、无渐变无阴影。<br>
         形象取自豹猫（ocelot）的头部轮廓，斑纹用两颗错位的实心圆点表示。</p>
    </div>
  </header>

  <section>
    <div class="label">主标 / Primary mark</div>
    <div class="card">
      {mark_l}
      {lockup_l}
      {wordmark}
    </div>
  </section>

  <section>
    <div class="label">应用图标 / App icon</div>
    <div class="card">
      {icon_d}
      {icon_l}
    </div>
  </section>

  <section>
    <div class="label">深色场景 / On dark</div>
    <div class="card dark">
      {mark_inv}
      {lockup_inv}
    </div>
  </section>

  <section>
    <div class="label">最小尺寸 / Scale ladder</div>
    <div class="scale">
      <div>{s24}<span>24 px</span></div>
      <div>{s32}<span>32 px</span></div>
      <div>{s40}<span>40 px</span></div>
      <div>{s56}<span>56 px</span></div>
      <div>{s72}<span>72 px</span></div>
    </div>
  </section>

  <section>
    <div class="label">使用规则 / Rules</div>
    <div class="notes">
      <div class="note"><b>只用一个颜色</b><span>图形永远单色（纯黑 #111111 或纯白）。不描边、不加渐变、不做双色。</span></div>
      <div class="note"><b>留白</b><span>四周留白不小于图形宽度的 1/4；与其它元素并排时优先用横向组合。</span></div>
      <div class="note"><b>最小尺寸</b><span>24 px 以上使用带斑版本；更小时改用无斑版 <code>ocelot-mark-solid.svg</code>。</span></div>
    </div>
  </section>

  <section>
    <div class="label">文件 / Files</div>
    <div class="files">
      ocelot-mark.svg · 主标（黑）<br>
      ocelot-mark-inverse.svg · 主标（白）<br>
      ocelot-mark-solid.svg · 无斑版，极小尺寸用<br>
      ocelot-icon.svg / ocelot-icon-light.svg · 应用图标（深底/浅底）<br>
      ocelot-lockup.svg / ocelot-lockup-inverse.svg · 横向组合<br>
      ocelot-wordmark.svg · 字标（已转曲，不依赖字体）
    </div>
  </section>

</div>
</body>
</html>
"""


def build() -> None:
    def sized(name: str, px: int) -> str:
        svg = load(name)
        import re
        svg = re.sub(r'width="[\d.]+"\s+height="[\d.]+"', f'width="{px}" height="{px}"', svg, count=1)
        return svg

    def sized_w(name: str, h: int) -> str:
        svg = load(name)
        import re
        m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
        w, hh = float(m.group(1)), float(m.group(2))
        ww = h * w / hh
        svg = re.sub(r'width="[\d.]+"\s+height="[\d.]+"', f'width="{ww:.0f}" height="{h}"', svg, count=1)
        return svg

    html = HTML.format(
        mark_big=sized("ocelot-mark.svg", 150),
        mark_l=sized("ocelot-mark.svg", 128),
        lockup_l=sized_w("ocelot-lockup.svg", 66),
        wordmark=sized_w("ocelot-wordmark.svg", 40),
        icon_d=sized("ocelot-icon.svg", 104),
        icon_l=sized("ocelot-icon-light.svg", 104),
        mark_inv=sized("ocelot-mark-inverse.svg", 128),
        lockup_inv=sized_w("ocelot-lockup-inverse.svg", 66),
        s24=sized("ocelot-mark.svg", 24),
        s32=sized("ocelot-mark.svg", 32),
        s40=sized("ocelot-mark.svg", 40),
        s56=sized("ocelot-mark.svg", 56),
        s72=sized("ocelot-mark.svg", 72),
    )
    (OUT / "preview.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    build()
    print("preview.html ok")
