import os
import datetime
from ffprobe import FFProbe
import uploader
import processing
import sys

from exif_write import ExifEdit
ZERO_PADDING = 6
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_FORMAT_2 = "%Y-%m-%dT%H:%M:%S.000000Z"

# 100ms, 200ms, ... 900ms, 1s, 2s, ... 120s
SENSIBLE_TIME_LAPSE_INTERVALS = [.1, .2, .3, .4, .5, .6, .7, .8, .9] + range(1, 120)

def timestamp_from_filename(filename,
                            start_time,
                            interval=1,
                            adjustment=1.0):
    seconds = (int(filename.lstrip("0").rstrip(".jpg"))) * \
        interval * adjustment
    return start_time + datetime.timedelta(seconds=seconds)


def timestamps_from_filename(full_image_list,
                             start_time,
                             interval=1,
                             adjustment=1.0):
    capture_times = []
    for image in full_image_list:
        capture_times.append(timestamp_from_filename(os.path.basename(image),
                                                     start_time,
                                                     interval,
                                                     adjustment))
    return capture_times


def sample_video(video_file,
                 import_path,
                 video_sample_interval,
                 video_start_time=None,
                 video_duration_ratio=1.0,
                 verbose=False):

    # basic check for all
    import_path = os.path.abspath(import_path)
    if not os.path.isdir(import_path):
        print("Error, import directory " + import_path +
              " doesnt not exist, exiting...")
        sys.exit()

    # command specific checks
    video_file = os.path.abspath(video_file) if video_file else None
    if video_file and not os.path.isfile(video_file):
        print("Error, video file " + video_file +
              " does not exist, exiting...")
        sys.exit()

    # check video logs
    video_upload = processing.video_upload(
        video_file, import_path, verbose)

    if video_upload:
        return

    sample_fps = calculate_sample_fps(video_file, video_sample_interval)

    video_file = video_file.replace(" ", "\ ")
    s = "ffmpeg -i {} -loglevel quiet -vf fps={} -qscale 1 {}/%0{}d.jpg".format(
        video_file, sample_fps, import_path, ZERO_PADDING)
    os.system(s)

    if video_start_time:
        video_start_time = datetime.datetime.utcfromtimestamp(
            video_start_time / 1000.)
    else:
        video_start_time = get_video_start_time(video_file)
        if not video_start_time:
            print("Warning, video start time not provided and could not be extracted from the video file, default video start time set to 0 milliseconds since UNIX epoch.")
            video_start_time = datetime.datetime.utcfromtimestamp(0)

    insert_video_frame_timestamp(import_path,
                                 video_start_time,
                                 video_sample_interval,
                                 video_duration_ratio,
                                 verbose)

    processing.create_and_log_video_process(
        video_file, import_path)


def get_video_duration(video_file):
    """Get video duration in seconds"""
    return float(FFProbe(video_file).video[0].duration)

def calculate_sample_fps(video_file, video_sample_interval):
    """
    Calculates frames per second video filter from sample interval.
    Automatically corrects for wrongly encoded time lapse videos.
    """

    default_fps = "1/{}".format(video_sample_interval)

    probed = FFProbe(video_file)
    if len(probed.meta) == 0:
        return default_fps

    video_duration = probed.video[0].durationSeconds()
    meta_duration = probed.meta[0].durationSeconds()
    if video_duration == meta_duration:
        return default_fps

    calculated_interval = meta_duration / probed.video[0].frames()
    likely_interval = round_to_sensible_interval(calculated_interval)
    if video_sample_interval < likely_interval:
        print("Error, sample interval smaller than (guessed) video interval. Video was "
            "recorded with approx. {} pictures per second.".format(likely_interval))
        sys.exit()

    video_fps = probed.video[0].framesPerSecond()
    return video_fps * likely_interval / video_sample_interval

def round_to_sensible_interval(calculated_interval):
    """
    Finds the next bigger interval from a guessed version.

    The last picture of a time lapse video might not be accounted for properly,
    making the video shorter than it should be. This may result in interval times
    such as "4.9s", instead of the more likely "5s".
    """

    if calculated_interval in SENSIBLE_TIME_LAPSE_INTERVALS:
        return calculated_interval

    for interval in SENSIBLE_TIME_LAPSE_INTERVALS:
        if(calculated_interval < interval):
            return interval

    return calculated_interval


def insert_video_frame_timestamp(import_path, start_time, sample_interval, duration_ratio=1.0, verbose=False):

    # get list of file to process
    frame_list = uploader.get_total_file_list(import_path)

    if not len(frame_list):
        if verbose:
            print("No video frames were sampled.")
        return

    video_frame_timestamps = timestamps_from_filename(frame_list,
                                                      start_time,
                                                      sample_interval,
                                                      duration_ratio)
    for image, timestamp in zip(frame_list,
                                video_frame_timestamps):
        try:
            exif_edit = ExifEdit(image)
            exif_edit.add_date_time_original(timestamp)
            exif_edit.write()
        except:
            if verbose:
                print("Could not insert timestamp into video frame " +
                      os.path.basename(image)[:-4])
            continue


def get_video_start_time(video_file):
    """Get video start time in seconds"""
    try:
        time_string = FFProbe(video_file).video[0].creation_time
        try:
            creation_time = datetime.datetime.strptime(
                time_string, TIME_FORMAT)
        except:
            creation_time = datetime.datetime.strptime(
                time_string, TIME_FORMAT_2)
    except:
        return None
    return creation_time
