"""Seed finder for Anno 1800.
Steps:
1) Baseline filtering:
     This brute forces all seeds (0 to 2147483647).
     Main focus is on the removal of unwanted islands.
     By default it removes all seeds with river islands (on old world + cape).
     The result is stored on disk in the seeds folder.
     Runtime is roughly 2000 seconds on a single core (but it uses all cores available).
2) Refinement:
     This only checks seeds that passed the baseline.
     Main focus is a scoring of the maps.
     We define a score for each island and get the best seeds that match our requirement.

Both steps offer these filter settings:
    1) Unwanted islands. These may not appear.
    2) Wanted islands, old world. All of these islands must appear.
    3) Wanted islands, cape. All of these must appear too.

However, refinement does not filter anything by default.
Instead, it works by sorting the resulting seeds by score:
    The score is the sum of island scores across old world and cape.
    The finder will then give back the highest scoring islands.
    You assign a score to each island based on personal preference
    and the output is the best scoring map.
    (Scoring is much slower than using filters, but should still take just a second.)

Baseline is basically preprocessing and only happens once.
Refinement is where you repeatedly change your requirements until you have just a handful of excellent seeds left.

By default, the finder uses the best seed from the refinement and directly draws the map.
You can adjust the plotcount variable to show multiple seeds, and to either show them directly or to save to disk.


If you need to abort baseline filtering for some reason, press Ctrl+C.
If you just kill the window instead, you will need to kill all (invisible) child processes from the task manager.

The baseline filtering can cause very large files when map and islands are small.
That is because it is far easier to get no rivers when a map has only few islands and many of them are small.
It is necessary to adjust the baseline to exclude more islands in such cases.

For the visualizer:
    Because each half of the map is drawn independently, the same island may appear larger or smaller.
    Essentially each world (old world vs cape) is zoomed in depending on how large the world is,
    so that takes up exactly half of the screen.
"""
import os
import numpy as np
import pandas as pd
import multiprocessing as mp
from queue import Empty
from ctypes import *
from visualize import Plot
import matplotlib.pyplot as plt
from util import Load, BinarizeWorld, BinarizeIslands, BinarizeWanted, CountDraws


# General map settings:
maptype     = "Corners"
mapsize     = "Large"
islandsize  = "Large"
difficulty  = "Normal"


# Define scores for refinement for each island.
# This is where you specify your personal island preference.
# The values below are the land tiles of each island.
# But that is only a rough guideline. Surely there are better values:
#   1) Harbor tiles can vary quite a bit (check the islandtiles folder).
#   2) Squareness of the island and cliffs can influence the choice.
# Unspecified islands have a score of 0.
# So if we only care about the largest islands, we can comment out the rest.
# This will find the best large islands, though medium islands may suffer.
# Optimization on small islands is not recommended because the finder does not consider them all.

scores = {'L1':  30572, 'L2':  27900, 'L3':  26692,
          'L4':  31494, 'L5':  28871, 'L6':  30504,
          'L7':  30217, 'L8':  28908, 'L9':  27467,
          'L10': 30536, 'L11': 29672, 'L12': 30257,
          'L13': 30337, 'L14': 29006, 'CI':  28406, 
##          'M1':  11610, 'M2':  14195, 'M3':  15821,
##          'M4':  16329, 'M5':  16236, 'M6':  16285,
##          'M7':  15140, 'M8':  15576, 'M9':  13038,
##          'S1':  2170,  'S2':  2918,  'S3':  3902,
##          'S4':  2751,  'S5':  3666,  'S6':  3193,
##          'S7':  2156,  'S8':  1734,  'S9':  2519,
##          'S10': 3560,  'S11': 1831,  'S12': 3598,
          }




### Example of an alternative approach with pandas.
### We directly work with the tiles.csv file but ignore small islands (going only from CI until M9).
### We want watertiles to be worth just 10% as much as land tiles.
### And tiles on medium islands shall be worth only 50% compared to large islands.
##scores = pd.read_csv("islandtiles/tiles.csv",index_col=0).loc["CI":"M9"]
##scores = scores.landtiles + 0.1 * scores.watertiles
##scores.loc["M1":"M9"] *= 0.5




# Islands that appear only on normal difficulty: M7 M8 M9 L1 L6 L7 L9 L10 L12 L13
# Islands that appear only on hard difficulty: M2R M4R M6R L3R L8R L9R L10R L14R




# Filtering is probably not needed for refinement.
unwanted = ""
wantedold = ""
wantedcape = ""




# Various output settings:
writecount = 15  # Only print the first ... seeds.
plotcount = 1
# Usage:
#   plotcount = 0    =>  Do not visualize anything. 
#   plotcount = 3    =>  Visualize 3 seeds and show them directly.
#   plotcount = -10  =>  Visualize 10 seeds and save them only.



# Not used for baseline or refinement. Only for the visualizer:
oldworldnpcs   = 2    # Does not include Archibald and pirate.
oldworldpirate = 1    # 0 or 1.





# Finder limitations:
#    Small island settings might not always work.
#    (Because some small islands are placed after NPCs,
#    and the NPC part is only implemented by the visualizer, not the finder.)
#
# Visualizer limitations:
#    The game slightly moves islands around from their original position.
#    And it occasionally rotates them.





# These settings work best for the largest maps on Large Large Normal; Corners, Atoll, Arc, Archipelago.
# (Though Archipelago is not recommended because it has 1 small island less than the others.)
# Try to keep the seeds below 100k (100,000). 
unwantedbaseline = "M1R M2R M3R M4R M5R M6R M7R M8R M9R CIR L1R L2R L3R L4R L5R L6R L7R L8R L9R L10R L11R L12R L13R L14R "
wantedbaselineold = ""
wantedbaselinecape = ""

### Snowflake Large Large Normal needs some finetuning already to keep the seeds down.
##wantedbaselineold += "L1 L6"
##unwantedbaseline  += "CI L8"

# Smaller maps will be even worse.





##########
# The setttings below should probably be kept unchanged:

# Number of cores/threads to use for baseline filtering.
# If your CPU has NO hyperthreading, you can remove the //2 to speed things up.
N_CPU = mp.cpu_count()//2

# Range of seeds to test.
START = 0
END = 0x80000000




###########################
###########################
assert 0 <= oldworldnpcs <= 2, "The number of NPCs in the old world must be one of: 0,1,2"
assert 0 <= oldworldpirate <= 1, "The number of pirates in the old world must be one of: 0,1"
def f(s):
    return s.replace(",","").strip().upper().split()
unwanted = f(unwanted)
wantedold = f(wantedold)
wantedcape = f(wantedcape)
unwantedbaseline = f(unwantedbaseline)
wantedbaselineold = f(wantedbaselineold)
wantedbaselinecape = f(wantedbaselinecape)


pd.options.display.max_colwidth = 100
pd.options.display.width  = 0
pd.options.display.max_rows  = 100


oldworld, cape, allislands = Load(maptype, mapsize, islandsize, difficulty)


# Do NOT substitute these variables into where they are used.
# Or the garbage collector will delete their data before C even runs.
roldworld, rcape = BinarizeWorld(oldworld), BinarizeWorld(cape)
rislandsbaseline = [BinarizeIslands(islands, unwantedbaseline) for islands in allislands]
rislands = [BinarizeIslands(islands, unwanted, scores) for islands in allislands]
rwanted,rwantedcape = BinarizeWanted(allislands, wantedold), BinarizeWanted(allislands, wantedcape)
rwantedbaseline, rwantedcapebaseline = BinarizeWanted(allislands, wantedbaselineold), BinarizeWanted(allislands, wantedbaselinecape)


def IslandArgs(allislands):
    rv = []
    for islands in allislands:
        rv += [islands.ctypes.data, len(islands)]
    return rv
def WorldArgs(world, normlen):
    return world.ctypes.data, normlen, len(world)
def WantedArgs(wanted):
    return wanted.ctypes.data, len(wanted)

# Push all the constant data into an easy to use argument.
fixedargsbaseline = [CountDraws(oldworld), CountDraws(cape),
                     *IslandArgs(rislandsbaseline),
                     *WorldArgs(*roldworld), *WorldArgs(*rcape),
                     *WantedArgs(rwantedbaseline), *WantedArgs(rwantedcapebaseline),
                     ]

fixedargs = [CountDraws(oldworld), CountDraws(cape),
             *IslandArgs(rislands),
             *WorldArgs(*roldworld), *WorldArgs(*rcape),
             *WantedArgs(rwanted), *WantedArgs(rwantedcape),
             ]





absdir = os.path.split(__file__)[0]
dll = CDLL(absdir+"/src/findseed.dll")

dll.find.restype = c_int32
dll.find.argtypes = [c_uint32, c_uint32, c_uint32, c_void_p,
                     c_uint32, c_uint32,
                     c_void_p, c_uint32, c_void_p, c_uint32, c_void_p, c_uint32,
                     c_void_p, c_uint32, c_uint32, c_void_p, c_uint32, c_uint32,
                     c_void_p, c_uint32, c_void_p, c_uint32,
                     ]


def Job(start, end, stepsize, queue, fixedargs = fixedargsbaseline, find=dll.find):
    """Worker task for the baseline. Feed the queue with good seeds."""
    null = c_void_p(0)  # Baseline does no scoring.
    while start < end:
        res = find(start, end, stepsize, null, *fixedargs)
        queue.put(res)
        if res == -1:
            break
        start = res+stepsize

def Score(seed):
    """Get the score for an accepted seed."""
    score = np.zeros(1,dtype=np.float32)
    seed = dll.find(seed, seed+1, 1, score.ctypes.data, *fixedargs)
    return score[0]
    



if __name__ == "__main__":
    setting = f"{maptype}_{mapsize}_{islandsize}_{difficulty}"
    baselinepath = f"seeds/{setting}.txt"

    try: os.mkdir("seeds")
    except FileExistsError: pass


    # If a baseline does not exist yet, create it.
    # Otherwise just use it, even if the current unwantedbaseline does not match the settings of the file.
    # This makes it easy to create a preset for each map type once and then ignore the unwantedbaseline completely.
    if not os.path.exists(baselinepath):
        print("No baseline found. Creating baseline in",baselinepath)
        # Baseline first, then refine.
        queue = mp.Queue()
        ps = []

        for tid in range(N_CPU):
            p = mp.Process(target=Job, args=(START+tid, END, N_CPU, queue))
            p.start()
            ps.append(p)

        workers = N_CPU
        seeds = []
        size = END-START
        try:
            counter = 0
            while workers:
                try:
                    seed = queue.get(timeout=1)  # This ensures that keyboard interrupts take just a second.
                except Empty:
                    continue
                
                if seed==-1:
                    workers-=1
                else:
                    seeds.append(seed)
                    if not counter % 100:
                        # Show the general progress but also get an estimate of the total number of seeds.
                        prog = seed/size
                        estimate = counter/prog
                        print(f"{prog:6.1%}  Estimated number of seeds: {estimate:,.0f}")
                    counter += 1
        except:
            raise
        finally:
            # Either successful finish or interrupted.
            for p in ps:
                p.terminate()
        # Success. Sort the numbers and save to file.
        with open(baselinepath,"w") as f:
            f.write(" ".join(unwantedbaseline)+" ; "+" ".join(wantedbaselineold)+" ; "+" ".join(wantedbaselinecape)+"\n")
            for seed in sorted(seeds):
                f.write(str(seed)+"\n")
        print("Baseline created.\n\n\n")

    print(f"Refinements, unwanted {unwanted}, wantedold {wantedold}, wantedcape {wantedcape}")
    
    # Refine on one core in Python.
    seeds = []
    score = np.zeros(1,dtype=np.float32)

    for i,seed in enumerate(open(baselinepath)):
        if not i: continue
        seed = int(seed)
        seed = dll.find(seed, seed+1, 1, score.ctypes.data, *fixedargs)
        if seed!=-1:
            seeds.append((seed,score[0]))

    print("Number of seeds:",len(seeds))
    seeds.sort(key=lambda x:-x[1])
    print(f"{'Seed:':>11} score")
    for seed,score in seeds[:writecount]:
        print(f"{seed:10}: {score:g}")
    seeds = [seed[0] for seed in seeds]
    
    if plotcount>0:
        for i,seed in enumerate(seeds):
            if i==plotcount: break
            Plot(seed, oldworld, cape, allislands, oldworldnpcs, oldworldpirate)
            plt.show()

    elif plotcount<0:
        plotcount *= -1
        print(f"Storing {min(plotcount,len(seeds))} results in folder (removing all previous):",setting)
        try: os.mkdir(setting)
        except FileExistsError:
            for name in os.listdir(setting):
                os.remove(setting+"/"+name)
        for i,seed in enumerate(seeds):
            if i==plotcount: break
            Plot(seed, oldworld, cape, allislands, oldworldnpcs, oldworldpirate)
            plt.savefig(f"{setting}/{seed}.png")
            plt.close()
            
        
            




















