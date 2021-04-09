"""
Script to preprocess SPCAM data.

Created on 2019-01-23-14-49
Author: Stephan Rasp, raspstephan@gmail.com
"""

from cbrain.imports import *
from cbrain.preprocessing.convert_dataset_20191113 import preprocess
from cbrain.preprocessing.convert_dataset_20191113 import preprocess_list
from cbrain.preprocessing.shuffle_dataset import shuffle
from cbrain.preprocessing.compute_normalization import normalize

# Set up logging, mainly to get timings easily.
logging.basicConfig(
    format='%(asctime)s %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p',
    level=logging.DEBUG
)


def main(args):
    """

    Returns
    -------

    """
    # Create training dataset
    if args.in_fns is not None:
        if args.path_PERC is not None:
            logging.info('Preprocess training dataset including output quantiles')
            preprocess(args.in_dir, args.in_fns, args.out_dir, args.out_fn, args.vars, path_PERC = args.path_PERC)
        else:
            logging.info('Preprocess training dataset')
            preprocess(args.in_dir, args.in_fns, args.out_dir, args.out_fn, args.vars)
    else:
        if args.list==True:
            preprocess_list(args.in_dir, args.out_dir, args.out_fn, args.vars, 
                            #list_xr = args.list_xr,
                            list_xr1 = args.list_xr1, list_xr2 = args.list_xr2,
                            lev_range=(0, 30), path_PERC=args.path_PERC)
        

    # Shuffle training dataset
    if args.shuffle:
        logging.info('Shuffle training dataset')
        shuffle(args.out_dir, args.out_fn, args.chunk_size)

    # Potentially
    if args.val_in_fns is not None:
        logging.info('Preprocess validation dataset')
        preprocess(args.in_dir, args.val_in_fns, args.out_dir, args.val_out_fn, args.vars)

    if args.norm_fn is not None:
        logging.info(f'Compute normalization file from {args.norm_train_or_valid}')
        normalize(
            args.out_dir,
            args.out_fn if args.norm_train_or_valid == 'train' else args.val_out_fn,
            args.norm_fn
        )

    logging.info('Finish entire preprocessing script.')


# Create command line interface
if __name__ == '__main__':

    p = ArgParser()
    p.add('-c', '--config_file', default='config.yml', is_config_file=True, help='Path to config file.')
    p.add('--vars', type=str, nargs='+', help='List of variables.')

    # For first file
    p.add('--in_dir', type=str, help='Directory containing SPCAM files.')
    p.add('--in_fns', type=str, help='SPCAM file names, * is allowed.')
    p.add('--out_dir', type=str, help='Directory where processed files will be stored.')
    p.add('--out_fn', type=str, help='Name of processed file.')

    # For shuffling
    p.add('--shuffle', dest='shuffle', action='store_true', help='Shuffle data along sample dimension.')
    p.set_defaults(shuffle=True)
    p.add('--chunk_size', type=int, default=10_000_000, help='Chunk size for shuffling.')

    # For potential validation file
    p.add('--val_in_fns', type=str, default=None, help='Validation: SPCAM file names, * is allowed.')
    p.add('--val_out_fn', type=str, default=None, help='Validation: Name of processed file.')

    # For a potential normalization file
    p.add('--norm_fn', type=str, default=None, help='Normalization: If given, compute normalization file.')
    p.add('--norm_train_or_valid', type=str, default='train', help='Compute normalization values from train or valid?')

    # tgb - 3/29/2021 - Optional path to read percentile distribution
    p.add('--path_PERC',type=str,default=None,help='Path to the pickled percentile array file describing the univariate output distribution')
    
    # If the files to open are provided as a list
    p.add('--list', dest='list', action='store_true', help='Provide files names as a list.')
    p.set_defaults(list=False)
    p.add('--list_xr1', type=str, default=None, help='File name list.')
    p.add('--list_xr2', type=str, default=None, help='File name list.')
    p.set_defaults(list_xr2=None)
#     p.add('--list_xr', type=list, help='File name lists.')
#     p.set_defaults(list_xr=None)
    
    
    args = p.parse_args()
    main(args)


