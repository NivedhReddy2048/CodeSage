# Third-party notices

CodeSage itself is MIT-licensed ([LICENSE](LICENSE)). The evaluation fixtures under
`eval/cases/` include small excerpts of other projects' source code: a changed file at
two commits and the diff between them. Each excerpt keeps its project's license, which
is credited below with the case ids that contain it. GPL-licensed projects are excluded.

Bugs were located with two research datasets, credited for their metadata (bug ids and
commit references); no dataset content beyond that is included:

- **BugsInPy**: Widyasari et al., "BugsInPy: A Database of Existing Bugs in Python
  Programs to Enable Controlled Testing and Debugging Studies", ESEC/FSE 2020.
  https://github.com/soarsmu/BugsInPy (the repository states no license; only its bug
  and commit references are used).
- **BugsJS**: Gyimesi et al., "BugsJS: a Benchmark of JavaScript Bugs", ICST 2019.
  https://bugsjs.github.io/ (MIT, Copyright (c) 2018 BugsJS).

## Projects whose code is included

| Project | License | Copyright | Cases |
|---|---|---|---|
| [thefuck](https://github.com/nvbn/thefuck) | MIT | Copyright (c) 2015-2022 Vladimir Iakovlev | bugsinpy-thefuck-3, -5, -21, -29, -32; clean-thefuck-9e8b4f5, clean-thefuck-e288343 |
| [PySnooper](https://github.com/cool-RR/PySnooper) | MIT | Copyright (c) 2019 Ram Rachum and collaborators | bugsinpy-pysnooper-3; clean-pysnooper-2b4b64b |
| [Express](https://github.com/expressjs/express) (and the BugsJS fork [BugsJS/express](https://github.com/BugsJS/express)) | MIT | Copyright (c) 2009-2014 TJ Holowaychuk <tj@vision-media.ca> | bugsjs-express-2, bugsjs-express-9; clean-express-511d9df |
| [HTTPie](https://github.com/httpie/cli) (formerly jakubroztocil/httpie) | BSD-3-Clause | Copyright © 2012-2022 Jakub Roztocil <jakub@roztocil.co> | bugsinpy-httpie-3; clean-cli-d35864e |
| [Cookiecutter](https://github.com/cookiecutter/cookiecutter) | BSD-3-Clause | Copyright (c) 2013-2026, Audrey M. Roy Greenfeld | bugsinpy-cookiecutter-3; clean-cookiecutter-4cae423 |
| [spaCy](https://github.com/explosion/spaCy) | MIT | Copyright (C) 2016-2024 ExplosionAI GmbH, 2016 spaCy GmbH, 2015 Matthew Honnibal | bugsinpy-spacy-2, bugsinpy-spacy-4 |
| [Black](https://github.com/psf/black) | MIT | Copyright (c) 2018 Łukasz Langa | bugsinpy-black-19; clean-black-2691902 |
| [Sanic](https://github.com/sanic-org/sanic) (formerly huge-success/sanic) | MIT | Copyright (c) 2016-present Sanic Community | bugsinpy-sanic-1; clean-sanic-2e5c288 |
| [Tornado](https://github.com/tornadoweb/tornado) | Apache-2.0 | Copyright 2009 Facebook (source headers; no NOTICE file) | bugsinpy-tornado-11; clean-tornado-f24ffd4 |
| [Luigi](https://github.com/spotify/luigi) | Apache-2.0 | Copyright 2012-2015 Spotify AB (source headers; no NOTICE file) | bugsinpy-luigi-28; clean-luigi-d2d3944 |
| [FastAPI](https://github.com/fastapi/fastapi) (formerly tiangolo/fastapi) | MIT | Copyright (c) 2018 Sebastián Ramírez | bugsinpy-fastapi-5; clean-fastapi-32d711f |
| [Scrapy](https://github.com/scrapy/scrapy) | BSD-3-Clause | Copyright (c) Scrapy developers. | bugsinpy-scrapy-18; clean-scrapy-ba10dcf |
| [Hexo](https://github.com/hexojs/hexo) (BugsJS fork [BugsJS/hexo](https://github.com/BugsJS/hexo)) | MIT | Copyright (c) 2012-2017 Tommy Chen | bugsjs-hexo-5 |
| [Karma](https://github.com/karma-runner/karma) (and the BugsJS fork [BugsJS/karma](https://github.com/BugsJS/karma)) | MIT | Copyright (C) 2011-2021 Google, Inc. | bugsjs-karma-1; clean-karma-1458267 |
| [Bower](https://github.com/bower/bower) (BugsJS fork [BugsJS/bower](https://github.com/BugsJS/bower)) | MIT | Copyright (c) 2013-present Twitter and other contributors | bugsjs-bower-3 |

Apache-2.0 files are included verbatim with their original license headers.

The full text of each license is in its project's repository, at the commit named in
the case's `case.json` (`source.url` and commit fields).
