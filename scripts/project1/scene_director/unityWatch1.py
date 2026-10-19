import time
P = op('/project1')
LOG = r"C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student-Work\e47db669-de3b-4ab0-adc2-e14604d170dc\scratchpad\unity_run.log"
try:
    if P.fetch('watch_on', 0.0) > 0.5 and P.fetch('watch_n', 0) < 20000:
        P.store('watch_n', P.fetch('watch_n', 0) + 1)
        sd = op('/project1/scene_director')
        sy = sd.op('oscSync1'); lt = sd.op('lineTrack1'); st = sd.op('standbyState1')
        fs = op('/project1/care_second_state/feeding_state/feedingState1')
        ws = op('/project1/care_second_state/feeding_state/wearinessState1')
        cb = op('/project1/care_third_state/card_sense/cardBranch1')
        key = '%d|%d|%d|%d|%d|%d|%d|%d' % (
            round(sy['unity_act'].eval()), round(sy['unity_line'].eval()),
            round(lt['td_act'].eval()), round(lt['td_line'].eval()),
            round(fs['feeding_count'].eval()), round(fs.fetch('burst_pub', 0.0)),
            round(cb['card_id'].eval()), round(st['standby'].eval()))
        if key != P.fetch('watch_prev', ''):
            P.store('watch_prev', key)
            a = key.split('|')
            msg = ('%s U=%s/%s TD=%s/%s feed=%s burst=%s card=%s standby=%s relief=%.2f cloud=%.2f heat=%.2f'
                   % (time.strftime('%H:%M:%S'), a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7],
                       ws['relief'].eval(), ws['cloud_alpha'].eval(),
                       op('/project1/effect_controller/effectController1')['sceneHeat'].eval()))
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(msg + chr(10))
        run(op('/project1/scene_director/unityWatch1').text, delayFrames=10)
except Exception as e:
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write('WATCH ERROR: ' + str(e) + chr(10))
