# Windows setup inside SERDA

1. Transfer this code folder only into an approved SERDA code directory. Do not transfer clinical datasets or results out of SERDA.
2. Use an approved 64-bit Python 3.10–3.12 environment. Create a virtual environment if permitted:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Arrange an approved offline wheel directory containing compatible Windows wheels for requirements.txt and their dependencies. Package wheels must match the Windows Python version and architecture. Provision packages using local wheels only:

```powershell
python -m pip install --no-index --find-links "<approved offline wheel directory>" -r requirements.txt
```

If SERDA already provides these packages, use that environment. The pipeline never installs packages automatically. xlrd is needed only for .xls; PyYAML reads config.yaml.

4. Run `python run_pipeline.py --help` to confirm imports and entry point. No datasets are read by --help.
5. Follow SERDA_execution_guide.md and select a separate approved output directory. All analysis runs on CPU.
