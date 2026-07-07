name: Build Hermes HAR Recorder

on:
  push:
    branches: [ main ]
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          
      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pyinstaller
          
      - name: Build Application
        run: python build.py
          
      - name: Upload Build (All dist)
        uses: actions/upload-artifact@v4
        with:
          name: HermesHARRecorder-Build
          path: dist/
          if-no-files-found: warn
