import sys
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QProgressBar,
    QLabel,
    QDialog,
    QRadioButton,
    QLineEdit,
    QDialogButtonBox,
    QFileDialog,
)
import os
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path
from plyer import notification

# Add project root to path to allow absolute imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.scripts import scrape_vald, cleanup_vald_images, chatgpt_generate, grok_generate

class TeamSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Team Selection")
        self.layout = QVBoxLayout(self)

        self.radio_prefix = QRadioButton("Start-text mode (e.g., 'KC Fusion')")
        self.radio_prefix.setChecked(True)
        self.layout.addWidget(self.radio_prefix)

        self.text_prefix = QLineEdit()
        self.text_prefix.setPlaceholderText("Enter starting text (e.g., KC Fusion)")
        self.layout.addWidget(self.text_prefix)

        self.radio_list = QRadioButton("Explicit list mode")
        self.layout.addWidget(self.radio_list)

        self.text_list = QLineEdit()
        self.text_list.setPlaceholderText("Enter comma-separated team names")
        self.layout.addWidget(self.text_list)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_selection(self):
        if self.radio_prefix.isChecked():
            return "prefix", [self.text_prefix.text()]
        else:
            teams = [team.strip() for team in self.text_list.text().split(",") if team.strip()]
            return "list", teams

class Worker(QThread):
    log_message = pyqtSignal(str, str)
    progress_updated = pyqtSignal(int)
    finished = pyqtSignal(bool)

    def __init__(self, team_selection_mode, team_values, data_dir):
        super().__init__()
        self.team_selection_mode = team_selection_mode
        self.team_values = team_values
        self.data_dir = data_dir
        self.is_running = True

    def run(self):
        try:
            data_path = Path(self.data_dir)
            if not data_path.exists() or not data_path.is_dir():
                raise FileNotFoundError(f"Data directory not found: {self.data_dir}")

            # Step 1: Scrape VALD
            self.log_message.emit("INFO", "Starting VALD Scraper...")
            try:
                success = scrape_vald.run_scraper(
                    team_selection_mode=self.team_selection_mode,
                    team_values=self.team_values,
                    output_dir=self.data_dir,
                    headless=True,
                    log_callback=self.log_message.emit,
                )
                if not success:
                    raise Exception("VALD Scraper returned a failure status.")
            except Exception as e:
                raise Exception(f"VALD Scraper failed: {e}")
            self.progress_updated.emit(25)
            if not self.is_running: return

            # Step 2: Cleanup images
            self.log_message.emit("INFO", "Starting image cleanup...")
            try:
                success = cleanup_vald_images.run_cleanup(
                    root=data_path,
                    teams_filter=[],
                    dry_run=False,
                    prune_empty_teams=True,
                    log_callback=self.log_message.emit,
                )
                if not success:
                    raise Exception("Image cleanup script returned a failure status.")
            except Exception as e:
                raise Exception(f"Image cleanup failed: {e}")
            self.progress_updated.emit(50)
            if not self.is_running: return

            # Step 3: ChatGPT generation
            self.log_message.emit("INFO", "Starting ChatGPT analysis generation...")
            try:
                success = chatgpt_generate.run_chatgpt_generation(
                    base_dir=self.data_dir,
                    log_callback=self.log_message.emit
                )
                if not success:
                    raise Exception("ChatGPT generation script returned a failure status.")
            except Exception as e:
                raise Exception(f"ChatGPT generation failed: {e}")
            self.progress_updated.emit(75)
            if not self.is_running: return

            # Step 4: Grok generation
            self.log_message.emit("INFO", "Starting Grok training program generation...")
            try:
                success = grok_generate.run_grok_generation(
                    base_dir_str=self.data_dir,
                    log_callback=self.log_message.emit
                )
                if not success:
                    raise Exception("Grok generation script returned a failure status.")
            except Exception as e:
                raise Exception(f"Grok generation failed: {e}")
            self.progress_updated.emit(100)

            self.finished.emit(True)

        except Exception as e:
            self.log_message.emit("ERROR", str(e))
            self.finished.emit(False)

    def stop(self):
        self.is_running = False


class ModernApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VALD Data Processor")
        self.setGeometry(100, 100, 800, 600)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(15)

        self.title_label = QLabel("VALD Data Processing Pipeline")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setObjectName("titleLabel")
        self.layout.addWidget(self.title_label)

        # Data directory selection
        self.data_dir_layout = QHBoxLayout()
        self.data_dir_label = QLabel("Data Directory:")
        self.data_dir_label.setObjectName("dataDirLabel")
        self.data_dir_input = QLineEdit()
        self.data_dir_input.setPlaceholderText("Select a directory to store data...")
        self.data_dir_button = QPushButton("Browse...")
        self.data_dir_button.clicked.connect(self.select_data_directory)
        self.data_dir_layout.addWidget(self.data_dir_label)
        self.data_dir_layout.addWidget(self.data_dir_input)
        self.data_dir_layout.addWidget(self.data_dir_button)
        self.layout.addLayout(self.data_dir_layout)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setObjectName("logDisplay")
        self.layout.addWidget(self.log_display)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.layout.addWidget(self.progress_bar)

        self.bottom_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Processing")
        self.start_button.setObjectName("startButton")
        self.start_button.setFixedHeight(40)
        self.start_button.clicked.connect(self.start_processing)
        self.bottom_layout.addWidget(self.start_button)

        self.layout.addLayout(self.bottom_layout)

        self.apply_stylesheet()
        self.worker = None

    def apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #2c3e50; }
            #titleLabel { font-size: 24px; font-weight: bold; color: #ecf0f1; padding-bottom: 10px; }
            #logDisplay { background-color: #34495e; color: #ecf0f1; border: 1px solid #2c3e50; border-radius: 5px; font-family: Consolas, Courier New, monospace; font-size: 14px; }
            QProgressBar { border: 1px solid #2c3e50; border-radius: 5px; text-align: center; color: #ecf0f1; background-color: #34495e; }
            QProgressBar::chunk { background-color: #2980b9; border-radius: 5px; }
            #startButton { background-color: #2980b9; color: white; font-size: 16px; font-weight: bold; border: none; border-radius: 5px; }
            #startButton:hover { background-color: #3498db; }
            #startButton:pressed { background-color: #2475a0; }
            #startButton:disabled { background-color: #566573; }
            QDialog { background-color: #34495e; }
            QRadioButton { color: #ecf0f1; }
            QLineEdit { border: 1px solid #2c3e50; border-radius: 5px; padding: 5px; color: #ecf0f1; background-color: #2c3e50; }
            #dataDirLabel { color: #ecf0f1; font-size: 14px; }
            #dataDirButton { background-color: #566573; color: white; border-radius: 5px; }
        """)

    def check_env_variables(self):
        required_vars = ["EMAIL", "PASSWORD", "OPENAI_API_KEY", "XAI_API_KEY"]
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            self.append_log_message("ERROR", f"Missing required environment variables in .env file: {', '.join(missing_vars)}")
            self.append_log_message("INFO", "Please check the README.md for setup instructions.")
            return False
        return True

    def select_data_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Data Directory")
        if directory:
            self.data_dir_input.setText(directory)

    def start_processing(self):
        if not self.check_env_variables():
            return

        data_dir = self.data_dir_input.text()
        if not data_dir:
            self.append_log_message("ERROR", "Please select a data directory.")
            return

        dialog = TeamSelectionDialog(self)
        if dialog.exec():
            team_mode, team_values = dialog.get_selection()
            if not team_values or not team_values[0]:
                self.append_log_message("ERROR", "No teams provided.")
                return

            self.start_button.setEnabled(False)
            self.progress_bar.setValue(0)
            self.log_display.clear()

            self.worker = Worker(team_mode, team_values, data_dir)
            self.worker.log_message.connect(self.append_log_message)
            self.worker.progress_updated.connect(self.update_progress)
            self.worker.finished.connect(self.on_finished)
            self.worker.start()

    def append_log_message(self, tag, message):
        self.log_display.append(f"[{tag.upper()}] {message}")

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def on_finished(self, success):
        self.start_button.setEnabled(True)
        title = "Processing Complete" if success else "Processing Failed"
        message = "All tasks completed successfully." if success else "One or more tasks failed. Check logs for details."

        self.append_log_message("SUCCESS" if success else "FAILURE", message)
        self.progress_bar.setFormat("Completed!" if success else "Failed!")

        try:
            notification.notify(
                title=title,
                message=message,
                app_name="VALD Data Processor"
            )
        except Exception as e:
            self.append_log_message("ERROR", f"Failed to send notification: {e}")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernApp()
    window.show()
    sys.exit(app.exec())
