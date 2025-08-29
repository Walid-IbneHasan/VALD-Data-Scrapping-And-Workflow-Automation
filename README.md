# VALD Data Processing Application

This application automates the process of scraping data from VALD, cleaning it, and generating analysis and training programs.

## Setup

### 1. Dependencies

This project uses Python. To install the required dependencies, run the following command in the project root directory:

```bash
pip install -r requirements.txt
```

### 2. Environment Variables

The application requires API keys and credentials to be set up in an environment file.

1.  Create a file named `.env` in the root of the project directory.
2.  Add the following variables to the `.env` file, replacing the placeholder values with your actual credentials:

    ```
    # VALD Hub Credentials
    EMAIL=your_email@example.com
    PASSWORD=your_password

    # OpenAI API Key (for analysis generation)
    OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

    # xAI API Key (for Grok training program generation)
    XAI_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    ```

## Usage

To run the application, execute the following command from the project root directory:

```bash
python src/main.py
```

This will open the graphical user interface.

1.  **Select Data Directory**: Click the "Browse..." button to choose a folder where all the scraped data and generated reports will be stored.
2.  **Start Processing**: Click the "Start Processing" button. A dialog will appear asking you to select the teams you want to process.
3.  **Monitor Progress**: The application will show real-time logs and a progress bar.
4.  **Completion**: You will receive a desktop notification when the entire process is complete.
