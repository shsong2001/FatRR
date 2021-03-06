from odbAccess import *
from abaqusConstants import *
import sys, getopt, os, string
import math
import rainflow_damage
import progress_bar

def getPath(job_id):
    odbPath = job_id + '.odb'
    new_odbPath = None
    print odbPath
    if isUpgradeRequiredForOdb(upgradeRequiredOdbPath=odbPath):
        print "Upgrade required"
        path,file = os.path.split(odbPath)
        file = 'upgraded_'+file
        new_odbPath = os.path.join(path,file)
        upgradeOdb(existingOdbPath=odbPath, upgradedOdbPath=new_odbPath)
        odbPath = new_odbPath
    else:
        print "Upgrade not required"
    return odbPath

def Nf(Smax, R):
    '''
    Calculate Nf for Inconel 625, room temperature
    '''
    log_Nf = 24.49 - 9.62*math.log10(Smax*pow((1-R),0.42))
    N = math.pow(10, log_Nf)
    return N

def life_at_f(f, Smax, T, R):
    n_1sigma = 0.6827*f*T
    N_1sigma = Nf(Smax, R)
    n_2sigma = 0.2718*f*T
    N_2sigma = Nf(2*Smax, R)
    n_3sigma = 0.0428*f*T
    N_3sigma = Nf(3*Smax, R)
    life = n_1sigma/N_1sigma + n_2sigma/N_2sigma + n_3sigma/N_3sigma
    return life
    
def calc_accumulated_damage(max_values, T, R):
    sum = 0.0
    for f, Smax in max_values:
        sum = sum + life_at_f(f, Smax, T, R)
    return sum
        
def odbMaxStress(job_id, exposure_time):

    odbPath = getPath(job_id)
    odb = openOdb(path=odbPath)
    
    MaxValues = {}
    for instance_name in odb.rootAssembly.instances.keys():
        MaxValues[instance_name] = {}

    # retrieve steps from the odb
    keys = odb.steps.keys()
    for key in keys:
        step = odb.steps[key]
        
        frames = step.frames

        sys.stdout.write('Working on step %s\n' % (key,))
        pb = progress_bar.ProgressBar(maxValue = len(frames), totalWidth = 60)
        for i in range(len(frames)):
        # for i in range(0,13):
            frame = frames[i]
            freq = frame.frameValue
            try:
                stress = frame.fieldOutputs['S']
        
                # Doesn't make too much sense to use an invariant on the stress in a RR analysis, but I need something
                for stressValue in stress.values:
                    instance = MaxValues[stressValue.instance.name]
                    if instance.has_key(stressValue.elementLabel):
                        element = instance[stressValue.elementLabel]
                        if element.has_key(freq):
                            element[freq] = max(stressValue.mises, element[freq])
                        else:
                            element[freq] = stressValue.mises
                    else:
                        instance[stressValue.elementLabel] = {}
                        
            except KeyError:
                print "fieldOutputs does not have S at frame %s" % (frame.frameId,)
            
            pb.updateAmount(i)
            sys.stdout.write('\r%s' % str(pb))
            sys.stdout.flush()
        sys.stdout.write('\n')
    odb.close()
    instances_to_delete = []
    def max_stress(a, b):
        if b > a:
            return b
        else:
            return a
    for instance_name, elements in MaxValues.iteritems():
        max_of_max = -1.0e20
        for element in elements.itervalues():
            maximum = reduce(max_stress, element.itervalues())
            #print 'maximum: %s' % (maximum,)
            # Deleting the instances without any values.
            # Only true for a random response analysis, adjust to taste
            max_of_max = max(maximum, max_of_max)
            #print 'max_of_max: %s' % (max_of_max,)
        if max_of_max < 0.0:
            instances_to_delete.append(instance_name)
    for instance_name in instances_to_delete:
        #print "deleting %s" % (instance_name,)
        del MaxValues[instance_name]    
                        
    dest = job_id + "_MaxStress.txt"
    output = open(dest,"w")
    output.write( 'instance,f (Hz),S (ksi)\n')
    mtrl = rainflow_damage.Material(A=pow(10.0,24.49), m = 9.62)
    for instance_name, elements in sorted(MaxValues.iteritems()):
        sys.stdout.write('Working on instance %s\n' % (instance_name,))
        damages = []
        pb = progress_bar.ProgressBar(maxValue = len(elements), totalWidth = 60)
        for i, (element_label, frequency_data) in enumerate(elements.iteritems()):
            #print 'element_label: %s, frequency_data: %s' % (element_label, frequency_data)
            vals = [(freq, val) for freq, val in frequency_data.iteritems()]
            vals.sort()
            #print 'vals: %s' % (vals,)
            s_PSD = rainflow_damage.StressPSD(vals)
            damages.append(rainflow_damage.damage(s_PSD, T=exposure_time, material = mtrl))
            pb.updateAmount(i)
            sys.stdout.write('\r%s' % str(pb))
            sys.stdout.flush()
        sys.stdout.write('\n')
        damages.sort(reverse=True) # Descending
        output.write("Accumulated damage for instance %s: %s\n" % (instance_name, damages[:10]))
    output.close()
        
if __name__ == '__main__':
        # Get command line arguments.
        
        usage = "usage: abaqus python <job name>"
        optlist, args = getopt.getopt(sys.argv[1:],'')
        JobID = args[0]
        T = float(args[1])
        if not JobID:
                print usage
                sys.exit(0)
        odbPath = JobID + '.odb'
        if not os.path.exists(odbPath):
                print "odb %s does not exist!" % odbPath
                sys.exit(0)
        excluded_instances = ['ASSY_6-1-1',]
        odbMaxStress(JobID, T)
