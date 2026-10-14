# Notice: licenses and attribution

The [MIT License](LICENSE) covers the **source code** of this project only. The repository also
ships character artwork and third-party runtimes that keep their own terms.

## Code

`main.py`, `live2d_renderer.html`, `tests/`, and the `companion.json` files in `models/` are
released under the MIT License.

## Character models

### `models/whale-girl/`: DS Whale Girl (default)

- **License:** [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
  (Attribution, NonCommercial, ShareAlike).
- **Copyright and credits:**
  - **上善无形**: original character design (OC 「溟月」), <https://space.bilibili.com/4456176>
  - **ZipZipPipe**: maid redesign with DeepSeek-inspired elements, <https://space.bilibili.com/4168597>
  - **氵六青**: Live2D model (rigging, motions, expressions), <https://space.bilibili.com/11272072>
- **Source:** `assets/model/` of
  [Andersen216/dsh-whale-girl-live2d](https://github.com/Andersen216/dsh-whale-girl-live2d)
  at commit [`cfaa7cd`](https://github.com/Andersen216/dsh-whale-girl-live2d/tree/cfaa7cd03ca21ab6a4a5e44a7b23ff2072d3bbf6/assets/model).
  That project generated `c_0120.model3.json`; see its
  [PROVENANCE.md](https://github.com/Andersen216/dsh-whale-girl-live2d/blob/cfaa7cd03ca21ab6a4a5e44a7b23ff2072d3bbf6/PROVENANCE.md)
  for per-file origin and the model author's original usage terms.
- **Changes:** the model files are redistributed unmodified. Only `companion.json` (motion roles and
  window size) was added.
- **Usage terms from the model author:** shared free of charge; resale or misappropriation is prohibited.
- This is fan-made artwork. The project is **not affiliated with or endorsed by DeepSeek**.
- Because of the NonCommercial term, this model must not be used in any paid product or service.
  Switch to another model (for example `LIVE2D_MODEL=hiyori`) for any commercial use.

### `models/hiyori/`: Hiyori Momose (alternative)

- © Live2D Inc., used under the Live2D Free Material License. See
  [`models/hiyori/LIVE2D_README.txt`](models/hiyori/LIVE2D_README.txt) and
  <https://www.live2d.com/en/download/sample-data/>.

## Runtime libraries (`vendor/`)

| Component | License | Copyright |
| --- | --- | --- |
| Live2D Cubism Core (`live2dcubismcore*.js`) | Live2D Proprietary Software License | Live2D Inc. |
| PixiJS 6.5.10 (`pixi.min.js`) | MIT | PixiJS contributors |
| pixi-live2d-display 0.4.0 (`cubism4.min.js`, `pixi-live2d-display.min.js`) | MIT | pixi-live2d-display contributors |

## Rights claims

If you believe any asset here infringes your rights, please
[open an issue](https://github.com/Mike-stone12/ai-companion/issues) naming the file. It will be
replaced or removed after verification.
