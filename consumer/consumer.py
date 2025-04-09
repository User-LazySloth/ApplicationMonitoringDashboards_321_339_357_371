from kafka import KafkaConsumer
import json
import logging
import psycopg2
from psycopg2 import sql
import os
import time

import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(level=logging.INFO)

DB_CONFIG = {
        'dbname': os.getenv('POSTGRES_DB', 'logs_db'),
        'user': os.getenv('POSTGRES_USER', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', 'password'),
        'host': os.getenv('POSTGRES_HOST', 'postgres'),
        'port': os.getenv('POSTGRES_PORT', '5432')
        }

def wait_for_postgres():
    max_attempts = 12
    for attempt in range(max_attempts):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            conn.close()
            logging.info("PostgreSQL is ready!")
            return
        except Exception as e:
            logging.warning(f"Attempt {attempt + 1}: PostgreSQL not ready - {e}")
            time.sleep(5)

    raise Exception("Could not connect to PostgreSQL after multiple attempts")

def create_tables():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS application_logs (
                           id SERIAL PRIMARY KEY,
                           timestamp TIMESTAMP,
                           request_id VARCHAR(255),
                           endpoint VARCHAR(50),
                           method VARCHAR(10),
                           response_time FLOAT
                           )
                       """)

        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS application_errors (
                           id SERIAL PRIMARY KEY,
                           timestamp TIMESTAMP,
                           error_type VARCHAR(255),
                           endpoint VARCHAR(50)
                           )
                       """)

        conn.commit()
        cursor.close()
        conn.close()
        logging.info("Tables created successfully")
    except Exception as e:
        logging.error(f"Error creating tables: {e}")

def insert_log(log_entry):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        cursor.execute(
                sql.SQL("INSERT INTO application_logs (timestamp, request_id, endpoint, method, response_time) VALUES (%s, %s, %s, %s, %s)"),
                (log_entry['timestamp'], log_entry['request_id'], log_entry['endpoint'], log_entry['method'], log_entry['response_time'])
                )

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error inserting log: {e}")

def insert_error(error_entry):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        cursor.execute(
                sql.SQL("INSERT INTO application_errors (timestamp, error_type, endpoint) VALUES (%s, %s, %s)"),
                (error_entry['timestamp'], error_entry['error_type'], error_entry['endpoint'])
                )

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Error inserting error: {e}")

def consume_logs():
    wait_for_postgres()
    create_tables()

    kafka_bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')

    try:
        consumer_config = {
            'bootstrap_servers': [kafka_bootstrap_servers],
            'group_id': 'log-processing-group',
            'auto_offset_reset': 'earliest',
            'value_deserializer': lambda x: json.loads(x.decode('utf-8')),
            'api_version': (2, 5, 0),
        }

        log_consumer = KafkaConsumer('application_logs', **consumer_config)
        error_consumer = KafkaConsumer('application_errors', **consumer_config)

        logging.info("Kafka consumers initialized successfully")

        for message in log_consumer:
            log_entry = message.value
            logging.info(f"Received log: {log_entry}")
            insert_log(log_entry)

        for message in error_consumer:
            error_entry = message.value
            logging.info(f"Received error: {error_entry}")
            insert_error(error_entry)

    except Exception as e:
        logging.error(f"Error in Kafka consumer: {e}")
        time.sleep(5)  
        consume_logs()  


def setup_logging():
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    file_handler = RotatingFileHandler('/consumer/consumer.log', maxBytes=1024*1024, backupCount=5)
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.INFO)
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)


if __name__ == '__main__':
    setup_logging()
    consume_logs()
