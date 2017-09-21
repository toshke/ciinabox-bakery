#!/usr/bin/env python

import sys
import yaml
import boto3

args_index_start = 0
if sys.argv[0] == 'regional_copies.py':
    args_index_start = args_index_start + 1
    
yml_file_name = sys.argv[0 + args_index_start]
source_region = sys.argv[1 + args_index_start]
destination_regions = sys.argv[2 + args_index_start]

print yml_file_name

bake_data = yaml.load(open(yml_file_name))

for ami in bake_data:
    ami_id = bake_data[ami][source_region]['ami']

    # discover users of the image
    ec2 = boto3.client('ec2', region_name=source_region)
    shared_users = ec2.describe_image_attribute(Attribute='launchPermission', ImageId=ami_id)
    shared_user_ids = list(map(lambda x: x['UserId'], shared_users['LaunchPermissions']))
    
    # start regional copy process
    for destination_region in destination_regions.split(','):
        try:
            # discover images
            dstEc2 = boto3.client('ec2', region_name=destination_region)
            image_data = ec2.describe_images(ImageIds=[ami_id])['Images'][0]
            if 'Description' in image_data:
                description = image_data['Description']
            else:
                description = image_data['Name']
                
            # copy image
            destination_image_id = dstEc2.copy_image(
                SourceImageId=ami_id,
                SourceRegion=source_region,
                Name=image_data['Name'],
                Description=description,
                ClientToken="copy{0}to{1}".format(ami_id, destination_region)
            )['ImageId']
            
            print ("Created copy of image {0}({1}): {2} in {3}".format(
                ami_id, source_region, destination_image_id, destination_region))
            
            # save data
            bake_data[ami][destination_region] = {'ami': destination_image_id}
        except Exception as ex:
            print "Failed to copy image {0} to region {1}\n{2}".format(ami_id, destination_region, ex)
    
    # wait for images to become available and share with list of users that source AMI is shared with
    for region in bake_data[ami]:
        if region != source_region:
            try:
                ami_id = bake_data[ami][region]['ami']
                ec2 = boto3.client('ec2', region_name=region)
                waiter = ec2.get_waiter('image_available')
                print "Waiting for 30 minutes max for image {0} in region {1} to become available".format(ami_id, region)
                waiter.wait(ImageIds=[ami_id], WaiterConfig={'Delay': 10, 'MaxAttempts': 180})
                
                print "Sharing {0} with users {1}..".format(ami_id, shared_user_ids)
                ec2.modify_image_attribute(
                    ImageId=ami_id,
                    UserIds=shared_user_ids,
                    OperationType='add',
                    Attribute='launchPermission'
                )
            except Exception as ex:
                print "Failed to share image {0} with users {1}\n{2}".format(ami_id, shared_user_ids, ex)

#write bake data back to file
with open(yml_file_name, 'w') as outfile:
        yaml.dump(bake_data, outfile, default_flow_style=False)
