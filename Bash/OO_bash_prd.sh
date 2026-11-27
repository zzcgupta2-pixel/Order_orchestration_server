#!/bin/bash

# ==============================
# Optimized Cron-Proof Bash Script: OO_bash_prd.sh
# ==============================

# -----------------------------
# Optional test mode
# -----------------------------
TEST_MODE=0
if [ "$1" == "--test" ]; then
    TEST_MODE=1
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running in TEST MODE." 
fi

# -----------------------------
# Define directories and log
# -----------------------------
#LOG_DIR="/home/VECVNET/zzasom/jupyter/01_Development_work/Black_Forecasting/Deployment/Logs"
LOG_DIR="/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Logs"
mkdir -p "$LOG_DIR"
chmod 755 "$LOG_DIR"

LOG_FILE="$LOG_DIR/bf_bash_prd_$(date '+%Y-%m-%d').log"
touch "$LOG_FILE"

if [ ! -w "$LOG_FILE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Cannot write to log file $LOG_FILE" >&2
    exit 1
fi

# -----------------------------
# Start log
# -----------------------------
echo "=============================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Script started" >> "$LOG_FILE"
echo "Running as user: $(whoami)" >> "$LOG_FILE"
echo "Environment PATH: $PATH" >> "$LOG_FILE"
echo "Test mode: $TEST_MODE" >> "$LOG_FILE"
echo "=============================================" >> "$LOG_FILE"

# -----------------------------
# Set PATH and activate Conda
# -----------------------------
export PATH=/home/VECVNET/zzasom/anaconda3/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
eval "$(/home/VECVNET/zzasom/anaconda3/bin/conda shell.bash hook)"
conda activate base

# -----------------------------
# Set Spark variables
# -----------------------------
export SPARK_MYSQL_JAR="/home/VECVNET/zzasom/spark/spark-3.3.0-bin-hadoop3/jars/mysql-connector-java-8.0.11.jar"
export PYSPARK_SUBMIT_ARGS="--jars $SPARK_MYSQL_JAR pyspark-shell"
export SPARK_HOME="/home/VECVNET/zzasom/spark/spark-3.3.0-bin-hadoop3"
export PYTHONPATH="$SPARK_HOME/python:$PYTHONPATH"

# -----------------------------
# Define Python scripts
# -----------------------------
PYTHON_SCRIPT_1="/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/Step1_VF_openorder.py"
PYTHON_SCRIPT_2="/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/Step2_ageing_stock.py"
PYTHON_SCRIPT_3="/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/scripts/Step3_run_data_cleaning.py"
PYTHON_SCRIPT_4="/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/Step4_inventory_reduction.py"
PYTHON_SCRIPT_5="/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build/Step5_main.py"
#PYTHON_SCRIPT_6="/home/VECVNET/zzasom/jupyter/01_Developement_work_QA/Chakshu_G/order_orchestration/order_orchestration_mannual/Build"


# -----------------------------
# Function to run Python scripts
# -----------------------------
run_python_script() {
    local script="$1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting $script..." >> "$LOG_FILE"
    START_TIME=$(date +%s)

    # Use nice to prioritize CPU if needed
    nice -n 0 /home/VECVNET/zzasom/anaconda3/bin/python3 "$script" >> "$LOG_FILE" 2>&1
    local status=$?

    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Finished $script in $DURATION seconds." >> "$LOG_FILE"

    if [ $status -ne 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $script failed with exit code $status!" >> "$LOG_FILE"
        tail -n 50 "$LOG_FILE" >> "$LOG_FILE"
        exit 1
    fi
}

# -----------------------------
# Run scripts sequentially
# -----------------------------
run_python_script "$PYTHON_SCRIPT_1"
run_python_script "$PYTHON_SCRIPT_2"
run_python_script "$PYTHON_SCRIPT_3"
run_python_script "$PYTHON_SCRIPT_4"
run_python_script "$PYTHON_SCRIPT_5"
#run_python_script "$PYTHON_SCRIPT_6"
# -----------------------------
# Log completion
# -----------------------------
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Script completed successfully." >> "$LOG_FILE"
echo "=============================================" >> "$LOG_FILE"

# -----------------------------
# Optional test mode: show tail
# -----------------------------
if [ $TEST_MODE -eq 1 ]; then
    echo "---------------- Log Tail ----------------"
    tail -n 20 "$LOG_FILE"
fi
