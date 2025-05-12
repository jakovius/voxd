## Whisp App Project

### Description
The Whisp App is a Python-based dictation, logging and note tool that uses whisper.cpp for speech-to-text transcription.

---

### The Core Process
... is the following sequence of steps, where config and dependencies are performed only once at the beginning of the application, and the rest of the sequence is performed once or multiple times as instructed in a particular usage mode.

0. **Configuration and Dependencies**: The application reads a configuration file to set up the environment and check dependencies (if verbosity requested via cli argument, displays diagnostics in a concise way).
1. **Recording**: The application captures a temporary audio from the microphone.
2. **Transcription**: The recorded audio is transcribed into text using the whisper.cpp model. If not in "hear" usage mode, the original whisper transcript (`orig_tscript`, containing the original timestamp) is saved or added in a temporary session (the session is the current run of the program) file. The returned transcript (`tscript`) for further processing is trimmed so that it does not contain the timestamp. The temporary audio is deleted.
- **AI Post-processing (optional)**: If configured, the transcribed text is processed using an AI model for additional functionality (e.g., summarization or keyword extraction).
3. **Clipboard**: The transcribed text is automatically copied to the clipboard.

---

### Additional Processing Features

#### Simulated Typing
- The transcribed text is typed into the currently focused application.
- It can type the transcribed text into any active application on any modern linux environment, allowing for seamless integration with existing workflows (handle and facilitate if X11 or Wayland, respectively).
- The typing speed and delay between keystrokes can be configured for optimal performance.

#### Session Logging
- In each usage mode, the transcripts are logged with timestamps into a string (each transcript into a new row).
- If session logging is called while running the program, at the end of the session the string's content is saved in a plain text file.
- Provide in the configuration file:
  - the path to the log file
  - if not provided, the log file is created in the current working directory with a default name containing a date and time prefix as `YYYY-MM-DD HHMM whisp_log.txt`).

#### AI Post-processing (AIPP)
- If called, it is run before the core clipboard automation.
- The returned transcript is processed using an AI model for additional functionality, e.g. summarization or keyword extraction.
- The output should be called `ai_output` and logged immediately after the corresponding transcript into the session log string using a prefix `[ai output]` for that processed transcript entry.
- Application's configuration file should be used to specify:
  - the provider, the model:
    - local Ollama server (with the currently served model)
    - or any reputable remote LLM API (Open AI, Anthropic, Grok, Google, Mistral ...) via a simple request/answer call
  - the default processing prompt, and any additional optional prompts that can be used instead of the default one

#### Collect Performance Data
- Optionally, the application can also be configured (via the configuration utility/file) to collect (or not to, which is default) the information on performance of the core process, and to run the AI post-processing on the transcribed text, for Testing/Diagnostics/Benchmarking purposes.
- This should be only available in the CLI and GUI modes (HEAR and WHISP modes need to run smoothly and quickly).
- The data that should be collected during the core process run should be added into a csv file (`performance_data.csv`) that is created upon setup of the application, and that is updated with each run of the core process (if at any point configured to do so).
- The csv file should contain the following columns: (detailed field list preserved from original input)
  - **date**: the date when the instance of the core process was started
- **rec_start_time**: the time when the recording in the core process was started
- **rec_end_time**: the time when the recording in the core process was ended
- **rec_dur**: the duration of the recording in the core process
- **trans_start_time**: the time when the transcription in the core process was started
- **trans_end_time**: the time when the transcription in the core process was ended
- **trans_dur**: the duration of the transcription in the core process
- **trans_sys_mem**: average % max system memory usage during transcription 
- **trans_sys_gpu**: average % of max gpu memory used during transcription
- **trans_sys_cpu**: average % of max CPU clock speed
- **trans_eff**: the efficiency of the transcription in the core process - transcription duration / `tscript` length, as transcription time per character output - basically the speech-to-text model efficiency
- **transcript**: the transcript (`tscript`) of the audio in the core process
- **usr_trans_acc**: user rating of the accuracy of the transcription in the core process - as the percentage of words that were correctly transcribed, compared to the original audio (user should be presented with the whole `tscript` in a pop-up in GUI mode or print-out if in CLI mode, and then prompted to enter this value, only if in testing mode or if data collection is enabled)
- **aipp_start_time**: (if aipp executed, else None) the time when the AI post-processing in the core process was started
- **aipp_end_time**: (if aipp executed, else None) the time when the AI post-processing in the core process was ended
- **aipp_dur**: (if aipp executed, else None) the duration of the AI post-processing in the core process
- **ai_model**: (if aipp executed, else None) the model used for the AI post-processing in the core process
- **ai_provider**: (if aipp executed, else None) values `local` or `remote`
- **ai_prompt**: (if aipp executed, else None) the prompt used for the AI post-processing in the core process
- **ai_transcript**: (if aipp executed, else None) the response from the AI post-processing in the core process
- **aipp_sys_mem**: (if aipp executed and locally run, else None) average % max system memory usage during transcription 
- **aipp_sys_gpu**: (if aipp executed and locally run, else None) average % of max gpu memory used during transcription
- **aipp_sys_cpu**: (if aipp executed and locally run, else None) average % of max CPU clock speed
- **aipp_eff**: (if aipp executed) the efficiency of the AI post-processing in the core process - AI post-processing duration / `ai_response` length, as AI post-processing time per character output - basically the AI model efficiency
- **sys_mem**: max system memory available
- **sys_gpu**: GPU memory available
- **sys_cpu**: CPU clock speed
- **total_dur**: the total duration of the core process run

---

### Usage Modes

#### HEAR Mode
- CLI-only, one-time run of the core process.
- Outputs transcript to clipboard.
- Can be used by other applications.

#### WHISP Mode
When run, the application is running in the background, showing its status in the system tray. Its main purpose is to provide the least invasive, simple, quick and efficient way to record dictaion audio, transcribe it into text and output it via simulated typing into the currently focused application, while not taking away users focus on the chosen application.
- It listens for a global hotkey to start/stop recording audio.
- When the hotkey or other start trigger is pressed, the core process is executed (recording/transcription/clipboard).
- optionally, the AI post-processing is executed (if configured to do so).
- The transcript is then typed into any currently focused input field or text input feature of any focused app (if any such in focus). 
- the system tray indicator is simple - shows one word, displaying current status and serving also as a control interface:
  - the user can click on it to show/hide the dropdown menu:
  - the first option is start/stop recording (changes based on the current status)
  - the second option is to show/hide the current content of the log string
  - the third option is to open settings that runs the configuration utility (discussed further in the configuration section), and then reinitiates the app in the same mode with the new settings
  - the fourth option is to run the testing/benchmarking utility (discussed further in the testing/benchmarking section)
  - the fifth option is to quit the application
  - the different statuses shown on the indicator
    - **Whisp**: Idle and ready. The application is not currently recording or transcribing. 
    - **Recording**: The application is actively recording audio and displays an orange-red, flashing circle character next to it, e.g. as a part of its string, by repeatedly exchanging it with a space character " ", or in a more efficient way.
    - **Transcribing**: The application is processing the recorded audio for transcription.  
    - **Typing**: The application is typing the transcribed text into the currently focused application.  

#### CLI Mode
The CLI mode is available when command-line interaction is desired. It allows for quick audio recording and transcription without the need for a graphical interface. In the essence, and for the sake of efficiency of the app, it is an extended version of the HEAR mode, with the following features:
- its purpose is to provide multiple cycles of the core process, that each time needs to be triggerd by the user
- the recording can be triggerd/stopped by the same global hotkey as in WHISP mode, or by input commands provided by the mode, in the terminal
- "r" command starts the recording
- pressing simply "enter" key stops the recording
- the rest of the core process runs automatically
- the transcript is printed in the terminal, and copied to the clipboard
- "l" command shows the current content of the log string, and offers to save it to a file with (Y/N) prompt, and then opens the system file manager to select the location and name of the file
- "x" command quits the application
- "h" command shows the list of available commands
- "cfg" command opens the configuration file in the default text editor (and shows a pop-up message that any new settings will be applied only after the application is restarted)

#### GUI Mode
The GUI mode provides a minimalistic graphic dark-mode interface which enables users to perform the core process repeatedly, upon request.
Features:
- one, central, pill-shaped button, that contains the current status string, like in the whisp mode. the button is only active for pressing when in "whisp" (idle) state, or in "recording" state (to stop recording)
- the global hotkey is applicable in this mode as well
- below the button, there is a text field that shows the first 30 characters of last transcript, and a small grey notice that says "copied to clipboard"
- below the text field, there is a small button that says "options"
  - the first option is "show log", and when pressed, it shows the current content of the log string, and offers to save it to a file with (Y/N) prompt, and then opens the system file manager to select the location and name of the file
  - the second option is "settings", and when pressed, shows a notice that any new settings will be applied only after the application is restarted, and it initiates execution of the configuration utility (discussed further in the configuration section)
  - the third option is "test", and when pressed, it initiates execution of the testing/benchmarking utility (discussed further in the configuration section)
  - below the settings button, there is a small button that says "quit", and when pressed, it quits the application

---

### Distribution, Installation & Portability

The Whisp App is designed for simplicity and minimal friction in installation and use. The following guidelines apply to its distribution and setup:

#### **Linux Distribution Options**
The primary distribution format is for Linux systems, with the following ways for installation:

##### 1. **AppImage Distribution (Recommended)**
- The application will be packaged as a self-contained `.AppImage` file for distribution, bundling all necessary dependencies *except* system-level essentials (like Python).
- Upon first run, the `.AppImage` will:
  - Check for Python availability.
  - Check for installed dependencies (whisper.cpp, Python modules).
  - Offer to launch the setup utility if anything is missing.

##### 2. **GitHub Clone + Setup Script**
- The application can be cloned directly from GitHub:
  ```bash
  git clone https://github.com/jacob8472/whisp.git
  cd whisp
  ./setup.sh
  ```
- The `setup.sh` utility:
  - Installs required system packages (if permissions allow).
  - Installs Python (if missing).
  - Installs or builds `whisper.cpp` in a local directory.
  - Sets up a virtual environment and installs Python dependencies.
  - Instruct the user to manually assign the global hotkey for recording in their OS.
  - Link `whisp` command to `/usr/local/bin`.  

### **Setup Utility**
- `setup.sh`: shell script that checks and installs system-level dependencies and builds whisper.cpp if needed.
- `setup_utils.py`: Python script for setting up virtual environments, installing requirements, and verifying access to devices and clipboard/keyboard APIs.

These scripts will:
- Detect if the system uses X11 or Wayland and install necessary dependencies accordingly.
- Confirm access to the microphone (e.g. using `pyaudio`, `sounddevice`, or `ffmpeg`).
- Validate whether clipboard functionality works (e.g., via `pyperclip`).
- Check the status of `whisper.cpp`, and download + build it locally if missing.  

### **Dependencies**
- Required system-level tools:
  - `ffmpeg` (for audio recording)
  - `git` (for cloning the repository)
  - `gcc`/`make` (for building whisper.cpp)
  - `xclip`, `wl-copy` or `pyperclip` for clipboard interaction (X11/Wayland)
  - `ydotools` for simulated typing (X11/Wayland)
  - Python 3.8+
  - Ollama server, OpenAI client if remote AI processing is used.    
  - Required Python packages (listed in `requirements.txt`):

### **Configuration Utility**
`config.py` should be included to manage the configuration file and the available models, by listing the current settings, and guiding and facilitating configuration overview and changes.
- The configuration file will be a simple JSON or YAML file, allowing users to specify:
  - Paths to the whisper binary and model files.
  - settings for the application (e.g., hotkeys, logging options).
  - AI processing settings (provider, model, prompts).
  - Clipboard and typing speed settings.
- The configuration utility will:
  - Read and write to the configuration file.
  - Validate settings and provide feedback on errors.
  - Allow users to select and configure available models for whisper.cpp.
- The utility will also provide a simple interface to fetch new models from the whisper.cpp repository or other sources.
- The configuration utility will be accessible via the WHISP, GUI, CLI (option "Settings") and the HEAR (calling with a specific CLI argument) modes, allowing users to modify settings without directly editing the config file.  

### **Testing/Diagnostics/Benchmarking Utility**
`test.py` should be included to provide a simple testing, diagnostics and benchmarking utility for the application.
- The application can be run in a this mode (only available in GUI and CLI modes) to test, diagnose and compare the performance of the transcription process in various configurations.
- there are several modes of use of the testing utility:
  - **Test**: run the core process and collect performance data
  - **Benchmark**: run the core process multiple times, on the same recorded audio input, with selected speech-to-text models and optionally AIPP models, and collect performance data the same way as if the data collection was enabled in the core process
  - **Analyze collected data**: read the performance data from the csv file and analyze it, providing a summary of the results
  - **Diagnostics**: run the core process and check for errors in the configuration file, dependencies, and system settings
- The testing mode can be used to check the performance of the application and its components, including:
  - the times taken for recording, transcription, and AIPP - with focus on transcription time minimization
  - the efficiency (vs hardware usage and output size) and accuracy of the transcription process
  - the efficiency (vs hardware usage and output size) of the AI post-processing  
  - 
### **Cross-Platform Considerations**
- Although primarily built for Linux, the architecture could allow porting to:
  - **Windows**, **macOS**, **Android** and **iOS**.

---

### Suggested Project Structure
```
whisp_app/
├── __main__.py
├── core/
│   ├── config.py
│   ├── logger.py
│   ├── recorder.py
│   ├── transcriber.py
│   ├── clipboard.py
│   └── typer.py
├── gui/
│   └── main.py
├── cli/
│   └── cli_main.py
├── whisp_mode/
│   └── tray.py
├── utils/
│   ├── setup_utils.py
│   ├── test.py
│   └── core_runner.py   ← orchestrates full core process
├── setup.sh
├── requirements.txt
└── config.yaml
```

---

End of Requirements

