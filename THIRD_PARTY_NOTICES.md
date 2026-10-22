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

The full text of each license is in its project's repository, at the commit named in
the case's `case.json` (`source.url` and commit fields).
