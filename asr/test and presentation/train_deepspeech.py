"""
File: train_deepspeech.py
Brief: Trains deepspeech 2 model on a dataset
Usage: python -m train_deepspeech <out_dir>
"""
import os
import logging
import argparse
import pathlib
import numpy as np
import warnings
warnings.filterwarnings('ignore')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
from keras.callbacks import CSVLogger
import tensorflow as tf

import deepasr as asr
from dataset_librispeech import LibriSpeechDataset
from dataset_radio import RadioDataset

SAMPLE_RATE = 16000   # Hz


def configure_logging(log_dir):
    """
    Create loggers to record training progress.
    @log_dir: Directory to write logs
    """
    logging.basicConfig(filename=os.path.join(log_dir, 'general.log'),
                        level=logging.DEBUG,
                        format='%(asctime)s %(message)s', 
                        datefmt='%d/%m/%Y %H:%M:%S')
    csv_logger =  CSVLogger(filename=os.path.join(log_dir, 'model_log.csv'),
                            append=True, 
                            separator=';')
    return csv_logger


def define_model(feature_type = 'spectrogram', multi_gpu = False):
    """
    Get the CTC pipeline
    @feature_type: the format of our dataset
    @multi_gpu: whether using multiple GPU
    """
    # audio feature extractor, this is build on asr built-in methods
    features_extractor = asr.features.preprocess(feature_type=feature_type, features_num=161,
                                                 samplerate=SAMPLE_RATE,
                                                 winlen=0.02,
                                                 winstep=0.025,
                                                 winfunc=np.hanning)
    
    # input label encoder
    alphabet_en = asr.vocab.Alphabet(lang='en')
    
    # training model
    model = asr.model.get_deepasrnetwork1(
        input_dim=161,
        output_dim=29,
        is_mixed_precision=True
    )
    
    # model optimizer
    optimizer = tf.keras.optimizers.Adam(
        learning_rate=1e-2,
        beta_1=0.9,
        beta_2=0.999,
        epsilon=1e-4
    )
    
    # output label deocder
    decoder = asr.decoder.GreedyDecoder()
    
    # CTC Pipeline
    pipeline = asr.pipeline.ctc_pipeline.CTCPipeline(
        alphabet=alphabet_en, features_extractor=features_extractor, model=model, optimizer=optimizer, decoder=decoder,
        sample_rate=SAMPLE_RATE, mono=True, multi_gpu=multi_gpu
    )
    return pipeline

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('dataset', choices=['librispeech', 'radio'])
    parser.add_argument('dataset_dir', type=pathlib.Path)
    parser.add_argument('output_dir', type=pathlib.Path)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.dataset == 'librispeech':
        dataset_loader = LibriSpeechDataset()
    else:
        dataset_loader = RadioDataset()

    dataset = dataset_loader.load_transcripts(args.dataset_dir)
    train_data = dataset.sample(frac=0.8, random_state=1234)    
    dataset_loader.describe(train_data, "Training")
 
    csv_logger = configure_logging(args.output_dir)
    pipeline = define_model(feature_type='spectrogram', multi_gpu=True)
    history = pipeline.fit(train_dataset=train_data, batch_size=64, epochs=500, callbacks=[csv_logger])
    pipeline.save(os.path.join(args.output_dir, 'checkpoints'))

