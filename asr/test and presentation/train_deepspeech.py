import os
import re
from datetime import datetime
import numpy as np
import pandas as pd
import tensorflow as tf
import librosa
# the build-in deepasr model in local
import deepasr as asr
import warnings
warnings.filterwarnings('ignore')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
# log document
import logging
from keras.callbacks import CSVLogger

log = "general.log"
logging.basicConfig(filename=log,level=logging.DEBUG,format='%(asctime)s %(message)s', datefmt='%d/%m/%Y %H:%M:%S')
csv_logger = CSVLogger('model_log.csv', append=True, separator=';')

def get_audio_trans_librispeech(filepath, audio_type='.flac'):
    """
    This function is to get audios and transcripts needed for training
    @filepath: the path of the dicteory
    """
    count, k, inp = 0, 0, []
    audio_name, audio_trans = [], []
    for dir1 in os.listdir(filepath):
        if dir1 == '.DS_Store': continue
        dir2_path = filepath + dir1 + '/'
        for dir2 in os.listdir(dir2_path):
            if dir2 == '.DS_Store': continue
            dir3_path = dir2_path + dir2 + '/'
            
            for audio in os.listdir(dir3_path):
                if audio.endswith('.txt'):
                    k += 1
                    trans_path = dir3_path + audio
                    with open(trans_path) as f:
                        line = f.readlines()
                        for item in line:
                            flac_path = dir3_path + item.split()[0] + audio_type
                            audio_name.append(flac_path)
                            
                            text = item.split()[1:]
                            text = ' '.join(text)
                            audio_trans.append(text)
    return pd.DataFrame({"path": audio_name, "transcripts": audio_trans})


def get_audio_trans_police(transcripts_dir):
    """
    This function is to get audios and transcripts needed for training
    Params:
        @transcripts_dir: path to directory with transcripts csvs
    """
    df = _match_police_audio_transcripts(transcripts_dir)
    df = _clean_transcripts(df)
    df = _clean_audiofiles(df)
    return df

def _clean_transcripts(df, remove_uncertain=True):
    """
    Filters out transcripts with marked uncertain passages
    Params:
        @df: data frame of transcribed utterances
    """
    # TODO: Some transcripts contain number. Need to replace using number -> word library.
    if remove_uncertain:
        has_x = df['transcripts'].str.contains('<x>') | df['transcripts'].str.contains('<X>')
        print(f'Discarding {has_x.sum()} uncertain transcripts.')
        df = df.loc[~ has_x]
    # NOTE: ctc_pipeline.py already ignores non-alphabet characters so we dont need to strip them.
    return df


def _clean_audiofiles(df):
    """
    Filters out non-existent and corrupted mp3's
    Params:
        @df: data frame of mp3 filepaths
    """
    mp3_exists = df['path'].transform(os.path.exists)
    print(f'Discarding {len(mp3_exists)-mp3_exists.sum()} missing mp3s')
    df = df.loc[mp3_exists]
    mp3_paths = df['path'].unique()
    valid_paths = set()
    for mp3 in mp3_paths:
        try:
            _ = librosa.core.load(mp3)
            valid_paths.add(mp3)
        except:
            pass
    mp3_isvalid = df['path'].transform(lambda x: x in valid_paths)
    print(f'Discarding {len(mp3_isvalid) - mp3_exists.sum()} corrupted mp3s')
    df = df.loc[mp3_isvalid]
    return df


def _match_police_audio_transcripts(ts_dir):
    """
    Matches ~second-long transcripts to ~30minute source audio file.
    Params:
        @ts_dir: Location of folder with transcripts csvs
    """
    ts_dir_files = os.listdir(ts_dir)
    pattern = "transcripts\d{4}_\d{2}_\d{2}.csv"
    ts_names = [name for name in ts_dir_files if re.match(pattern, name)]
    ts_paths = [os.path.join(ts_dir, name) for name in ts_names]
    audio_dfs = [_match_utterance_to_audio(ts_path) for ts_path in ts_paths]
    return pd.concat(audio_dfs, ignore_index=True)


def _match_utterance_to_audio(ts_path):
    """
    Extracts mp3 path, utterance timestamp, and duration from transcript metadata
    Params:
        @ts_path: Location of transcript csv
    """
    df = pd.read_csv(ts_path)
    audio_dir = '/project/graziul/data'
    root = pd.Series([audio_dir]*len(df))
    ext = pd.Series([".mp3"]*len(df))
    fmt_month = df['month'].astype(str).str.pad(2, 'left', '0')
    fmt_day = df['day'].astype(str).str.pad(2, 'left', '0')
    fmt_year = df['year'].astype(str)
    fmt_date = fmt_year.str.cat([fmt_month, fmt_day], sep="_")
    aud_name = df['file'].str.extract("(\d+-\d+-\d+)", expand=False).str.cat(ext)
    aud_fp = root.str.cat([df['zone'], fmt_date, aud_name], sep=os.sep)
    zero_date = datetime(1900, 1, 1)
    start_offset = pd.to_datetime(df['start_dt']) - zero_date
    return pd.DataFrame({'path': aud_fp, 
                         'offset': start_offset.dt.seconds, 
                         'duration': df['length'], 
                         'transcripts': df['transcription']})
  

def get_config(feature_type = 'spectrogram', multi_gpu = False):
    """
    Get the CTC pipeline
    @feature_type: the format of our dataset
    @multi_gpu: whether using multiple GPU
    """
    # audio feature extractor, this is build on asr built-in methods
    features_extractor = asr.features.preprocess(feature_type=feature_type, features_num=161,
                                                 samplerate=16000,
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
        sample_rate=16000, mono=True, multi_gpu=multi_gpu
    )
    return pipeline


if __name__ == "__main__":
    #audio_trans = get_audio_trans_librispeech('audio data/LibriSpeech/train-clean-100/')
    audio_trans = get_audio_trans_police('/project/graziul/transcripts')
    train_data = audio_trans[audio_trans['transcripts'].str.len() < 100]
    train_data = train_data.head()
    pipeline = get_config(feature_type='fbank', multi_gpu=False)
    #history = pipeline.fit(train_dataset=train_data, batch_size=128, epochs=500, callbacks=[csv_logger])
    history = pipeline.fit(train_dataset=train_data, batch_size=64, epochs=10, callbacks=[csv_logger])
    #project_path = '/project/graziul/ra/shiyanglai/experiment1'
    project_path = '/project/graziul/ra/echandler/experiment1'
    pipeline.save(project_path + 'checkpoints')
